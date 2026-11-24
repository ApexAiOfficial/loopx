"""Public-safe projection for controller-declared Todo completion validation."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .contract import (
    TODO_STATUS_DONE,
    normalize_todo_claimed_by,
    normalize_todo_id,
)


_DECLARATION_FIELDS = (
    "validation_command",
    "validation_command_argv",
    "validation_label",
    "validation_timeout_seconds",
)


def completion_validation_declaration(item: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize private execution detail for local effect resolution and hashing."""

    command_value = item.get("validation_command")
    command = command_value.strip() if isinstance(command_value, str) else command_value
    if command == "":
        command = None
    argv: Any = item.get("validation_command_argv")
    if isinstance(argv, str):
        compact = argv.strip()
        if not compact:
            argv = None
        else:
            try:
                argv = json.loads(compact)
            except ValueError:
                argv = compact
    elif isinstance(argv, tuple):
        argv = list(argv)
    label = item.get("validation_label")
    if label == "":
        label = None
    timeout: Any = item.get("validation_timeout_seconds")
    if isinstance(timeout, str) and timeout.strip().isdigit():
        timeout = int(timeout.strip())
    elif timeout == "":
        timeout = None
    declaration = {
        "validation_command": command,
        "validation_command_argv": argv,
        "validation_label": label,
        "validation_timeout_seconds": timeout,
    }
    return (
        declaration
        if any(item.get(field) not in (None, "") for field in _DECLARATION_FIELDS)
        else None
    )


def completion_validation_declaration_sha256(
    declaration: dict[str, Any],
) -> str:
    payload = json.dumps(
        declaration,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def project_completion_validation_authority(item: dict[str, Any]) -> dict[str, Any]:
    """Replace private validation execution details with one authority marker."""

    projected = dict(item)
    declaration = completion_validation_declaration(projected)
    for field in _DECLARATION_FIELDS:
        projected.pop(field, None)
    if declaration is not None:
        projected["completion_validation_required"] = True
        projected["completion_validation_sha256"] = (
            completion_validation_declaration_sha256(declaration)
        )
        projected.setdefault("completion_validation_revision", 0)
        projected.setdefault("completion_validation_revision_history", [])
    return projected


def pending_completion_validation_todo(
    todo_summary: dict[str, Any] | None,
    *,
    todo_id: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any] | None:
    """Return a projected open Todo whose controller validation is required.

    Two scopes, because the caller either names the Todo or only names a lane:

    - Exact scope (``todo_id`` given): the settlement binds that Todo, so its
      claim state is irrelevant and an unclaimed Todo still fences.
    - Lane scope (only ``agent_id`` given): the fence exists so an agent cannot
      claim accountable evidence while *its own* controller-validated Todo is
      open. An unclaimed Todo owns no lane, so it is nobody's own work and must
      not fence a different lane's writeback.
    """

    if not isinstance(todo_summary, dict):
        return None
    expected_todo_id = normalize_todo_id(todo_id)
    expected_agent_id = normalize_todo_claimed_by(agent_id)
    lane_scoped = not expected_todo_id and bool(expected_agent_id)
    items = todo_summary.get("items")
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        item_todo_id = normalize_todo_id(item.get("todo_id"))
        if expected_todo_id and item_todo_id != expected_todo_id:
            continue
        item_agent_id = normalize_todo_claimed_by(item.get("claimed_by"))
        if lane_scoped:
            if item_agent_id != expected_agent_id:
                continue
        elif (
            expected_agent_id
            and item_agent_id
            and item_agent_id != expected_agent_id
        ):
            continue
        if item.get("completion_validation_required") is not True:
            continue
        if item.get("done") is True or item.get("status") == TODO_STATUS_DONE:
            continue
        return item
    return None
