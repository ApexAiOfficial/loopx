from __future__ import annotations

import pytest

from loopx.control_plane.todos import completed_archive
from loopx.control_plane.todos.completed_archive import (
    archive_completed_todo_lines,
    completed_todo_archive_warning,
    completed_todo_count,
)
from loopx.status import parse_active_state_todos


def _fixture_text() -> str:
    return (
        "# Goal\n\n"
        "## Agent Todo\n\n"
        "- [x] Completed work.\n"
        "  <!-- loopx:todo todo_id=todo_done status=done -->\n"
        "- [-] Deferred work.\n"
        "  <!-- loopx:todo todo_id=todo_deferred status=deferred "
        "resume_when=todo_done:todo_done -->\n\n"
        "## Completed Work Archive\n"
    )


def test_completed_archive_keeps_deferred_todo_active() -> None:
    original = _fixture_text()
    parsed = parse_active_state_todos(original)["agent_todos"]

    assert parsed["done_count"] == 2
    assert parsed["deferred_count"] == 1
    assert completed_todo_count(parsed) == 1
    warning = completed_todo_archive_warning(parsed, max_active_done_todos=0)
    assert warning is not None
    assert warning["active_done_count"] == 1

    result = archive_completed_todo_lines(original.splitlines(), max_active_done=0)
    updated = "\n".join(result["lines"])

    assert result["moved_count"] == 1
    assert updated.index("Deferred work.") < updated.index("## Completed Work Archive")
    assert updated.index("## Completed Work Archive") < updated.index("Completed work.")
    projected = parse_active_state_todos(updated)["agent_todos"]
    deferred = next(
        item for item in projected["items"] if item["todo_id"] == "todo_deferred"
    )
    assert deferred["status"] == "deferred"
    assert deferred["archive_state"] == "active"


def test_completed_todo_count_fails_closed_for_invalid_summary_counts() -> None:
    assert completed_todo_count(None) == 0
    assert completed_todo_count({"done_count": 1}) == 0
    assert completed_todo_count({"done_count": "invalid", "deferred_count": 1}) == 0
    assert completed_todo_count({"done_count": 1, "deferred_count": 2}) == 0


def test_legacy_archive_calls_typed_selector_once_per_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict]] = []

    def select(method: str, params: dict) -> dict:
        calls.append((method, params))
        return {
            "schema_version": "loopx_coordination_todo_archive_selection_v0",
            "role": "agent",
            "active_done_before": 2,
            "active_done_after": 1,
            "max_active_done": 1,
            "moved_count": 1,
            "moved_todo_ids": ["todo_first"],
            "retained_standing_decision_count": 0,
        }

    monkeypatch.setattr(completed_archive, "effect_runtime_result", select)
    original = (
        "# Goal\n\n## Agent Todo\n\n"
        "- [x] First.\n"
        "  <!-- loopx:todo todo_id=todo_first status=done -->\n"
        "- [x] Second.\n"
        "  <!-- loopx:todo todo_id=todo_second status=done -->\n\n"
        "## Completed Work Archive\n"
    )

    result = archive_completed_todo_lines(
        original.splitlines(),
        max_active_done=1,
    )

    assert len(calls) == 1
    assert calls[0][0] == "todo.archive.select"
    assert [todo["todo_id"] for todo in calls[0][1]["todos"]] == [
        "todo_first",
        "todo_second",
    ]
    assert all(todo["archive_state"] == "active" for todo in calls[0][1]["todos"])
    assert result["moved_count"] == 1
    updated = "\n".join(result["lines"])
    assert updated.index("Second.") < updated.index("First.")
