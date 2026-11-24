"""Host IO adapter for the typed, saved-plan promotion operation.

This module deliberately does not interpret the review carrier, invent an
operation id, or decide whether a persisted fence permits recovery.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..effect_runtime import effect_runtime_result


def execute_reviewed_coordination_promotion(
    *,
    reviewed_plan: Mapping[str, Any],
    runtime_root: Path,
    goal_id: str,
    action: str,
    execute: bool,
    projection: Mapping[str, Any] | None = None,
    source_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "schema_version": "loopx_reviewed_coordination_promotion_operation_v0",
        "action": action,
        "runtime_root": str(runtime_root.expanduser().absolute()),
        "goal_id": goal_id,
        "reviewed_plan": dict(reviewed_plan),
        "execute": execute,
    }
    if projection is not None:
        request["projection"] = dict(projection)
    if source_snapshot is not None:
        request["source_snapshot"] = dict(source_snapshot)
    result = effect_runtime_result(
        "coordination.local_authority.promotion_reviewed", request, timeout=30.0
    )
    if not isinstance(result, dict):
        raise ValueError("reviewed promotion runtime returned an invalid result")
    return result
