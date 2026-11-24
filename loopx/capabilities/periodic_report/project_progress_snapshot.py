from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ...control_plane.todos.active_state_todo_parser import parse_active_state_todos
from ...control_plane.todos.todo_semantics import todo_item_is_actionable_open
from ...control_plane.effect_runtime import EffectRuntimeRejected, effect_runtime_result
from .todo_source import read_report_todo_source
from .incremental import select_incremental_project_progress


def build_project_progress_snapshot(
    *,
    registry_path: Path,
    goal_id: str,
    runtime_root: Path | None = None,
    agent_id: str,
    completed_at: str,
    publication_cursor: Mapping[str, Any] | None = None,
    goal_cursors: Sequence[Mapping[str, Any]] | None = None,
    available_capabilities: Any = None,
    rollout_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Build a bounded public-safe progress snapshot at a stage boundary."""

    fields, _ = read_report_todo_source(
        registry_path=registry_path,
        goal_id=goal_id,
        runtime_root=runtime_root,
        rollout_events=rollout_events,
        available_capabilities=available_capabilities,
    )
    return build_project_progress_snapshot_from_fields(
        fields=fields,
        goal_id=goal_id,
        agent_id=agent_id,
        completed_at=completed_at,
        publication_cursor=publication_cursor,
        goal_cursors=goal_cursors,
    )


def build_project_progress_snapshot_from_state(
    *,
    state_text: str,
    goal: Mapping[str, Any],
    state_path: Path,
    goal_id: str,
    agent_id: str,
    completed_at: str,
    publication_cursor: Mapping[str, Any] | None = None,
    goal_cursors: Sequence[Mapping[str, Any]] | None = None,
    available_capabilities: Any = None,
    rollout_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Legacy text adapter; provider-aware callers use the shared Todo source.

    Evidence is selected for the Goal, not for the calling lane: every Agent's
    eligible rows are reportable and ``agent_id`` only ranks the reporting
    Agent's own rows first, so a multi-Agent Goal does not lose peer progress
    and the bounded outcome cap never evicts the reporter's own outcomes. A row
    no Agent claimed has no producer and stays out of the report.

    Resume-gated todos are judged with the same typed resume evidence the
    scheduler consumes: ``rollout_events`` feeds ``pr_merged`` gates and
    ``available_capabilities`` feeds ``capacity_available`` gates. Callers
    that cannot supply authoritative evidence omit both, and unsatisfied
    external gates stay excluded (fail-closed) instead of being guessed.
    """

    parsed = parse_active_state_todos(
        state_text,
        goal=dict(goal),
        state_path=state_path,
        item_limit=None,
        rollout_events=rollout_events,
        available_capabilities=available_capabilities,
    )
    return build_project_progress_snapshot_from_fields(
        fields=parsed,
        goal_id=goal_id,
        agent_id=agent_id,
        completed_at=completed_at,
        publication_cursor=publication_cursor,
        goal_cursors=goal_cursors,
    )


def build_project_progress_snapshot_from_fields(
    *,
    fields: Mapping[str, Any],
    goal_id: str,
    agent_id: str,
    completed_at: str,
    publication_cursor: Mapping[str, Any] | None = None,
    goal_cursors: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Select facts from one complete evaluated snapshot, then apply publication history."""
    items = list((fields.get("agent_todos") or {}).get("items") or [])
    selection_fields = (
        "todo_id",
        "status",
        "claimed_by",
        "updated_at",
        "completed_at",
        "action_kind",
        "task_class",
    )
    try:
        selected = effect_runtime_result(
            "capabilities.periodic_report.progress.select",
            {
                "schema_version": "periodic_report_progress_selection_request_v0",
                "agent_id": agent_id,
                "completed_at": completed_at,
                "items": [
                    {
                        **{key: item.get(key) for key in selection_fields},
                        "actionable": todo_item_is_actionable_open(item),
                    }
                    for item in items
                ],
            },
        )
    except EffectRuntimeRejected as error:
        raise ValueError(str(error)) from error
    if (
        not isinstance(selected, dict)
        or selected.get("schema_version")
        != "periodic_report_progress_selection_result_v0"
    ):
        raise ValueError("periodic-report progress selection result mismatch")
    progress_items: list[dict[str, Any]] = []
    for outcome in selected["outcomes"]:
        index = outcome["rank"]
        item = items[outcome["index"]]
        summary = " ".join(
            str(
                item.get("evidence") or item.get("note") or item.get("text") or ""
            ).split()
        )
        title = " ".join(str(item.get("text") or "Completed project work").split())
        progress_items.append(
            {
                "item_id": f"completed_{index + 1}",
                "title": title[:240],
                "summary": summary[:360] or "Validated completion is durably recorded.",
                "content_kind": "outcome",
                "value_rank": 10 + index,
                "source_ref": f"todo:{item['todo_id']}",
                "completed_at": outcome["completed_at"],
            }
        )
    if selected["next_index"] is not None:
        item = items[selected["next_index"]]
        progress_items.append(
            {
                "item_id": "next_action",
                "title": "Next action",
                "summary": " ".join(str(item.get("text") or "").split())[:360],
                "content_kind": "next_action",
                "value_rank": 90,
                "source_ref": f"todo:{item['todo_id']}",
            }
        )
    if not progress_items:
        return None
    snapshot: dict[str, Any] = {
        "schema_version": "periodic_report_project_progress_projection_v0",
        "goal_id": goal_id,
        "observed_at": completed_at,
        "language": "zh-CN",
        "items": progress_items,
    }
    if publication_cursor is not None or goal_cursors:
        # A lane that has never published still must not re-announce what the
        # Goal already announced, so the peer baseline applies without one.
        incremental = select_incremental_project_progress(
            snapshot,
            cursor=publication_cursor,
            goal_cursors=goal_cursors,
        )
        if incremental is None:
            return None
        snapshot = incremental
    outcome_items = [
        item for item in snapshot["items"] if item.get("content_kind") == "outcome"
    ][:6]
    next_items = [
        item for item in snapshot["items"] if item.get("content_kind") == "next_action"
    ][:1]
    snapshot["items"] = outcome_items + next_items
    return snapshot


__all__ = [
    "build_project_progress_snapshot",
    "build_project_progress_snapshot_from_state",
]
