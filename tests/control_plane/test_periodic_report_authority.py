"""The reporting consumer never treats a stale display as Todo authority."""

import json

import pytest

from canonical_authority_fixture import (
    initialize_canonical_authority,
    isolate_sqlite_runtime,
)
from loopx.capabilities.periodic_report.project_progress_snapshot import (
    build_project_progress_snapshot,
)
from loopx.control_plane.coordination.runtime_shadow import (
    build_todo_runtime_shadow_projection,
)
from loopx.control_plane.todos.active_state_todo_parser import parse_active_state_todos

GOAL = "report-authority"
STAGE = "2026-09-21T12:00:00Z"


def workspace(tmp_path, monkeypatch, provider, *, empty=False, decision=False):
    if provider == "sqlite":
        isolate_sqlite_runtime(tmp_path, monkeypatch)
    state = tmp_path / "state.md"
    text = (
        "# Report fixture\n\n## Agent Todo\n"
        "- [x] Canonical finished work.\n"
        "  <!-- loopx:todo todo_id=todo_real status=done task_class=advancement_task "
        "claimed_by=reporter updated_at=2026-09-21T10:00:00Z no_followup=true -->\n"
    )
    state.write_text(text)
    records = parse_active_state_todos(text, item_limit=None)["agent_todos"]["items"]
    if decision:
        user_text = (
            "## User Todo\n- [x] Reject the report payload.\n"
            "  <!-- loopx:todo todo_id=todo_decision status=done task_class=user_gate "
            "action_kind=approve_periodic_report_payload decision_scope=other:action:report-1 "
            "decision_outcome=reject bound_agent=reporter updated_at=2026-09-21T10:00:00Z -->\n"
        )
        user = parse_active_state_todos(user_text, item_limit=None)["user_todos"][
            "items"
        ][0]
        user.update(archive_state="archive", source_section="Completed Work Archive")
        records.append(user)
    projection = build_todo_runtime_shadow_projection(
        goal_id=GOAL, todos=[] if empty else records, handoff_mode="soft_claim"
    )
    runtime = tmp_path / "runtime"
    initialize_canonical_authority(
        runtime, GOAL, projection, state_path=state, provider=provider
    )
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "common_runtime_root": str(runtime),
                "goals": [
                    {"id": GOAL, "repo": str(tmp_path), "state_file": str(state)}
                ],
            }
        )
    )
    return registry, state, runtime


@pytest.mark.parametrize("provider", ["file", "sqlite"])
@pytest.mark.parametrize("display", ["missing", "stale", "malformed"])
def test_snapshot_uses_authority_without_repairing_display(
    tmp_path, monkeypatch, provider, display
):
    registry, state, _ = workspace(tmp_path, monkeypatch, provider)
    if display == "missing":
        state.unlink()
    elif display == "malformed":
        state.write_bytes(b"\xff\xfe")
    else:
        state.write_text("## Agent Todo\n- [ ] Stale display work.\n")
    before = state.read_bytes() if state.exists() else None
    snapshot = build_project_progress_snapshot(
        registry_path=registry, goal_id=GOAL, agent_id="reporter", completed_at=STAGE
    )
    assert [row["source_ref"] for row in snapshot["items"]] == ["todo:todo_real"]
    assert (state.read_bytes() if state.exists() else None) == before


@pytest.mark.parametrize("provider", ["file", "sqlite"])
def test_empty_authority_does_not_resurrect_markdown_outcome(
    tmp_path, monkeypatch, provider
):
    registry, _, _ = workspace(tmp_path, monkeypatch, provider, empty=True)
    assert (
        build_project_progress_snapshot(
            registry_path=registry,
            goal_id=GOAL,
            agent_id="reporter",
            completed_at=STAGE,
        )
        is None
    )


@pytest.mark.parametrize("provider", ["file", "sqlite"])
def test_unavailable_authority_is_not_empty_or_legacy(tmp_path, monkeypatch, provider):
    from loopx.capabilities.periodic_report import todo_source
    from loopx.control_plane.coordination.local_authority import (
        LocalCoordinationAuthorityUnavailable,
    )

    registry, _, _ = workspace(tmp_path, monkeypatch, provider)

    def unavailable(**kwargs):
        raise LocalCoordinationAuthorityUnavailable(
            "unavailable", code="test_outage", payload={}
        )

    monkeypatch.setattr(todo_source, "read_canonical_todos_if_promoted", unavailable)
    with pytest.raises(LocalCoordinationAuthorityUnavailable):
        build_project_progress_snapshot(
            registry_path=registry,
            goal_id=GOAL,
            agent_id="reporter",
            completed_at=STAGE,
        )


@pytest.mark.parametrize("provider", ["file", "sqlite"])
def test_approval_retry_reads_retained_canonical_decision_and_explicit_runtime(
    tmp_path, monkeypatch, provider
):
    from loopx.capabilities.periodic_report.pending_intent import (
        _superseding_approval_revision,
    )
    from loopx.control_plane.coordination.local_authority import (
        read_canonical_todos_if_promoted,
    )
    import hashlib

    registry, state, runtime = workspace(tmp_path, monkeypatch, provider, decision=True)
    config = json.loads(registry.read_text())
    todo_id = "todo_decision"
    row = next(
        t
        for t in read_canonical_todos_if_promoted(runtime_root=runtime, goal_id=GOAL)[
            "todos"
        ]
        if t["todo_id"] == todo_id
    )
    config["common_runtime_root"] = str(tmp_path / "wrong-runtime")
    registry.write_text(json.dumps(config))
    state.unlink()
    expected = hashlib.sha256(f"{todo_id}:{row['updated_at']}".encode()).hexdigest()[
        :16
    ]
    assert (
        _superseding_approval_revision(
            registry_path=registry,
            runtime_root=runtime,
            goal_id=GOAL,
            agent_id="reporter",
            receipt={
                "status": "approval_pending",
                "approval_scope": "other:action:report-1",
            },
        )
        == expected
    )
