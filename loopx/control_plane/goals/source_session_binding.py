from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ...file_lock import exclusive_cross_runtime_file_lock
from ..effect_runtime import effect_runtime_result
from ..projects.registry_codec import (
    SOURCE_SESSION_PROFILE_ID,
    source_session_registry_transaction,
)
from ..runtime.time import now_local_iso
from .source_session_registry_state import (
    canonical_digest,
    current_goal_ref,
    exact_goal_ref,
    guard_path,
    prior_operation_receipt,
    required_list,
    session_binding_records,
)


@dataclass(frozen=True, slots=True)
class SessionBindingRequest:
    registry_path: Path
    session_id: str
    goal_id: str
    goal_instance_id: str
    operation_id: str


def _session_request_digest(
    request: SessionBindingRequest,
    *,
    operation: Literal["bind", "unbind"],
) -> str:
    return canonical_digest(
        {
            "schema_version": "loopx_source_session_request_v1",
            "operation": operation,
            "operation_id": request.operation_id,
            "session_id": request.session_id,
            "goal_ref": exact_goal_ref(
                request.goal_id,
                request.goal_instance_id,
            ),
        }
    )


def _session_result(
    request: SessionBindingRequest,
    *,
    operation: Literal["bind", "unbind"],
    receipt: dict[str, Any],
    replayed: bool,
    project_id: str,
) -> dict[str, Any]:
    binding = {
        "session_id": request.session_id,
        "foreground_goal_ref": copy.deepcopy(receipt["goal_ref"]),
    }
    return {
        "ok": True,
        "schema_version": (
            "loopx_session_binding_v1"
            if operation == "bind"
            else "loopx_session_unbinding_v1"
        ),
        "changed": bool(receipt["changed"]),
        "replayed": replayed,
        "registry": str(request.registry_path),
        "project_id": project_id,
        "goal_ref": copy.deepcopy(receipt["goal_ref"]),
        "binding": (
            binding if operation == "bind" else binding if receipt["changed"] else None
        ),
        "receipt": copy.deepcopy(receipt),
        "execution_authority": False,
    }


def _commit_project_session_operation(
    request: SessionBindingRequest,
    *,
    operation: Literal["bind", "unbind"],
) -> dict[str, Any]:
    request_digest = _session_request_digest(request, operation=operation)
    requested_goal_ref = exact_goal_ref(
        request.goal_id,
        request.goal_instance_id,
    )
    guard = guard_path(request.registry_path, request.goal_id)
    with exclusive_cross_runtime_file_lock(
        guard,
        operation="source_session_goal_lifetime",
    ):
        with source_session_registry_transaction(
            request.registry_path,
            operation=f"source_session_project_{operation}",
        ) as transaction:
            registry = transaction.payload_copy()
            active_goal_ref, goal = current_goal_ref(
                registry,
                goal_id=request.goal_id,
            )
            bindings = session_binding_records(registry)
            receipts = required_list(registry, "session_receipts")
            lifetime_receipts = required_list(registry, "lifetime_receipts")
            if (
                prior_operation_receipt(
                    lifetime_receipts,
                    operation_id=request.operation_id,
                )
                is not None
            ):
                raise ValueError(
                    "source-session operation_id was reused across lifecycle operations"
                )
            current_binding = next(
                (
                    binding
                    for binding in bindings
                    if binding.get("session_id") == request.session_id
                ),
                None,
            )
            prior_receipt = prior_operation_receipt(
                receipts,
                operation_id=request.operation_id,
            )
            decision = effect_runtime_result(
                f"goal.source_session.{operation}.decide",
                {
                    "profile_id": registry["profile_id"],
                    "operation_id": request.operation_id,
                    "request_digest": request_digest,
                    "session_id": request.session_id,
                    "requested_goal_ref": requested_goal_ref,
                    "current_goal_ref": active_goal_ref,
                    "current_binding": current_binding,
                    "prior_receipt": prior_receipt,
                    "binding_count": len(bindings),
                    "receipt_count": len(receipts),
                },
            )
            if not isinstance(decision, dict):
                raise RuntimeError("source-session decision must be an object")
            if decision.get("kind") == "reject":
                raise ValueError(
                    f"source-session {operation} rejected: {decision.get('code')}"
                )
            project_id = str(goal.get("project_id") or "")
            if not project_id:
                raise ValueError("source-session Goal is missing project_id")
            if decision.get("kind") == "replay":
                replay_receipt = decision.get("receipt")
                if not isinstance(replay_receipt, dict):
                    raise RuntimeError("source-session replay omitted its receipt")
                return _session_result(
                    request,
                    operation=operation,
                    receipt=replay_receipt,
                    replayed=True,
                    project_id=project_id,
                )
            if decision.get("kind") != "commit":
                raise RuntimeError("source-session decision kind is unsupported")
            changed = decision.get("changed")
            if not isinstance(changed, bool):
                raise RuntimeError("source-session commit omitted changed")

            if operation == "bind":
                next_binding = {
                    "session_id": request.session_id,
                    "foreground_goal_ref": requested_goal_ref,
                }
                registry["session_bindings"] = [
                    binding
                    for binding in bindings
                    if binding.get("session_id") != request.session_id
                ] + [next_binding]
            elif changed:
                registry["session_bindings"] = [
                    binding
                    for binding in bindings
                    if binding.get("session_id") != request.session_id
                ]

            receipt = {
                "schema_version": "loopx_source_session_receipt_v1",
                "operation": operation,
                "operation_id": request.operation_id,
                "request_digest": request_digest,
                "session_id": request.session_id,
                "goal_ref": requested_goal_ref,
                "changed": changed,
                "committed_at": now_local_iso(),
            }
            registry["session_receipts"] = [*receipts, receipt]
            registry["updated_at"] = receipt["committed_at"]
            transaction.commit(registry)
            return _session_result(
                request,
                operation=operation,
                receipt=receipt,
                replayed=False,
                project_id=project_id,
            )


def commit_project_session_binding(
    request: SessionBindingRequest,
) -> dict[str, Any]:
    return _commit_project_session_operation(request, operation="bind")


def commit_project_session_unbinding(
    request: SessionBindingRequest,
) -> dict[str, Any]:
    return _commit_project_session_operation(request, operation="unbind")


def resolve_source_session_project(
    *,
    registry: dict[str, Any],
    registry_path: Path,
    goal_id: str | None,
    goal_instance_id: str | None,
    session_id: str | None,
) -> dict[str, Any]:
    """Classify exact source-session evidence without granting execution."""

    if registry.get("profile_id") != SOURCE_SESSION_PROFILE_ID:
        raise ValueError("source-session registry profile is unsupported")
    if goal_id is None or goal_instance_id is None:
        raise ValueError(
            "source-session resolution requires goal_id and goal_instance_id"
        )
    requested = exact_goal_ref(goal_id, goal_instance_id)
    current, goal = current_goal_ref(registry, goal_id=goal_id)
    project_id = str(goal.get("project_id") or "")
    if not project_id:
        raise ValueError("source-session Goal is missing project_id")
    resolution = "current" if requested == current else "mismatched"
    retired = required_list(registry, "retired_goal_instances")
    if any(item.get("goal_ref") == requested for item in retired):
        resolution = "retired"
    binding = None
    if session_id is not None:
        binding = next(
            (
                item
                for item in session_binding_records(registry)
                if item.get("session_id") == session_id
            ),
            None,
        )
        if binding is None:
            resolution = "absent"
        elif binding.get("foreground_goal_ref") != requested:
            resolution = "mismatched"
        elif requested == current:
            resolution = "current"
    return {
        "ok": resolution == "current",
        "schema_version": "loopx_project_resolution_v1",
        "resolution": resolution,
        "source": "source_session",
        "registry": str(registry_path),
        "project_id": project_id if resolution == "current" else None,
        "goal_ref": requested,
        "current_goal_ref": current,
        "binding": copy.deepcopy(binding),
        "execution_authority": False,
    }
