from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..effect_runtime import EffectRuntimeRejected, effect_runtime_result
from ...history import decode_registry_snapshot
from ...registry import registry_goals
from .activation import GoalActivationState, goal_activation_state
from .activation_service import (
    GoalActivationAuthorityRoute,
    GoalActivationAuthorityRouteMode,
    GoalActivationSourceStatus,
    _source_and_target,
    goal_activation_source_fingerprint,
)


GOAL_ACTION_PROJECTION_REQUEST_SCHEMA_VERSION = (
    "loopx_goal_action_projection_request_v3"
)
GOAL_ACTION_CATALOG_SCHEMA_VERSION = "loopx_goal_action_catalog_v1"


def _goal(payload: Mapping[str, Any], goal_id: str) -> Mapping[str, Any]:
    goal = next(
        (
            item
            for item in registry_goals(dict(payload))
            if str(item.get("id") or "") == goal_id
        ),
        None,
    )
    if goal is None:
        raise ValueError(f"goal id not found in registry: {goal_id}")
    return goal


def _identity_fact(goal: Mapping[str, Any]) -> dict[str, Any]:
    fact = {"goal_id": goal.get("id")}
    if "goal_instance_id" in goal:
        fact["goal_instance_id"] = goal.get("goal_instance_id")
    return fact


def _identity_observation(
    *,
    route: GoalActivationAuthorityRoute,
    requested_goal: Mapping[str, Any],
    source_goal: Mapping[str, Any] | None,
) -> dict[str, Any]:
    binding_owner = (
        "source_registry"
        if route.mode is GoalActivationAuthorityRouteMode.REQUESTED_TO_GLOBAL
        else "global_projection"
    )
    if route.source_status is GoalActivationSourceStatus.AVAILABLE:
        if source_goal is None:
            raise RuntimeError("available Goal source route has no Goal")
        authority: dict[str, Any] = {
            "kind": "present",
            "goal": _identity_fact(source_goal),
        }
    elif route.source_status is GoalActivationSourceStatus.GOAL_MISSING:
        authority = {"kind": "absent"}
    else:
        authority = {
            "kind": "unavailable",
            "reason": route.source_status.value,
        }
    return {
        "binding_owner": binding_owner,
        "authority": authority,
        "binding": _identity_fact(requested_goal),
    }


def build_goal_action_catalog(
    *,
    registry_path: Path,
    goal_id: str,
    runtime_root_override: str | None = None,
) -> dict[str, Any]:
    """Adapt one stable registry snapshot into the TS-owned action catalog."""

    normalized_goal_id = str(goal_id or "").strip()
    if not normalized_goal_id:
        raise ValueError("goal id is required")
    requested_registry = Path(registry_path).expanduser().resolve()
    requested_bytes = requested_registry.read_bytes()
    requested_payload = decode_registry_snapshot(
        requested_registry,
        requested_bytes,
    )
    requested_goal = _goal(requested_payload, normalized_goal_id)
    current_state = goal_activation_state(requested_goal)
    target_state = (
        GoalActivationState.STOPPED
        if current_state is GoalActivationState.ACTIVE
        else GoalActivationState.ACTIVE
    )
    authority_route = _source_and_target(
        registry_path=requested_registry,
        goal_id=normalized_goal_id,
        target_state=target_state,
        runtime_root_override=runtime_root_override,
    )
    source_bytes = authority_route.source_registry.read_bytes()
    source_payload = decode_registry_snapshot(
        authority_route.source_registry,
        source_bytes,
    )
    action_goal = _goal(source_payload, normalized_goal_id)
    source_state = goal_activation_state(action_goal)
    source_goal = (
        action_goal
        if authority_route.source_status is GoalActivationSourceStatus.AVAILABLE
        else None
    )
    fingerprint = goal_activation_source_fingerprint(
        goal_id=normalized_goal_id,
        source_registry=authority_route.source_registry,
        source_bytes=source_bytes,
    )
    try:
        result = effect_runtime_result(
            "goal.operator_actions.project",
            {
                "schema_version": GOAL_ACTION_PROJECTION_REQUEST_SCHEMA_VERSION,
                "goal_id": normalized_goal_id,
                "registry_locator": str(requested_registry),
                "runtime_root_locator": authority_route.sync_runtime_root,
                "activation_state": source_state.value,
                "state_fingerprint": fingerprint,
                "identity_observation": _identity_observation(
                    route=authority_route,
                    requested_goal=requested_goal,
                    source_goal=source_goal,
                ),
            },
        )
    except EffectRuntimeRejected as exc:
        raise ValueError(str(exc)) from None
    if not isinstance(result, Mapping) or (
        result.get("schema_version") != GOAL_ACTION_CATALOG_SCHEMA_VERSION
    ):
        raise RuntimeError("TypeScript Goal action catalog shape mismatch")
    actions = result.get("actions")
    if not isinstance(actions, list) or not all(
        isinstance(item, Mapping) for item in actions
    ):
        raise RuntimeError("TypeScript Goal action list shape mismatch")
    return dict(result)


def render_goal_action_catalog_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Goal Actions",
        "",
        f"- ok: `{str(payload.get('ok')).lower()}`",
        f"- goal: `{payload.get('goal_id')}`",
        f"- activation_state: `{payload.get('activation_state')}`",
    ]
    actions = payload.get("actions")
    if isinstance(actions, list):
        lines.extend(["", "## Available actions", ""])
        for action in actions:
            if isinstance(action, Mapping):
                lines.append(
                    f"- `{action.get('action_id')}` — {action.get('label')}"
                )
    if payload.get("error"):
        lines.extend(["", f"Error: {payload.get('error')}"])
    return "\n".join(lines).rstrip() + "\n"
