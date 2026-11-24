"""Fail-closed normalization for repeated GitHub status-check attempts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any


def _attempt_timestamp(item: Mapping[str, Any]) -> float:
    for field in ("startedAt", "createdAt"):
        value = str(item.get(field) or "").strip()
        if not value:
            continue
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
    return 0.0


def _attempt_identity(item: Mapping[str, Any]) -> tuple[str, ...] | None:
    name = str(
        item.get("name")
        or item.get("context")
        or item.get("workflowName")
        or ""
    ).strip().casefold()
    workflow = str(item.get("workflowName") or "").strip().casefold()
    typename = str(item.get("__typename") or "check").strip().casefold()
    if name and workflow:
        return (typename, workflow, name)

    context = str(item.get("context") or "").strip().casefold()
    app = item.get("app")
    app = app if isinstance(app, Mapping) else {}
    app_identity = str(app.get("slug") or app.get("name") or "").strip().casefold()
    if context and app_identity:
        return (typename, app_identity, context)
    return None


def latest_check_attempts(
    items: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Drop provably superseded attempts while retaining ambiguous rows."""

    latest_by_identity: dict[tuple[str, ...], float] = {}
    for item in items:
        identity = _attempt_identity(item)
        timestamp = _attempt_timestamp(item)
        if identity is not None and timestamp:
            latest_by_identity[identity] = max(
                latest_by_identity.get(identity, 0.0), timestamp
            )

    effective: list[dict[str, Any]] = []
    for item in items:
        identity = _attempt_identity(item)
        timestamp = _attempt_timestamp(item)
        if (
            identity is None
            or not timestamp
            or timestamp >= latest_by_identity[identity]
        ):
            effective.append(item)
    return effective, len(items) - len(effective)
