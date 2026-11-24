"""A refused Turn settlement names the typed input the writer still owes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.control_plane.work_items.delivery_outcome import (
    explain_turn_scoped_settlement_gap,
    qualifies_turn_scoped_settlement,
)
from loopx.state_refresh import refresh_state_run

GOAL_ID = "settlement-diagnosis-fixture"
WORK_ITEM_ID = "todo_owed_settlement"
TURN_INSTANCE_ID = "2026-09-20T16:30:59.996Z"


def _blocked_observation(**overrides: object) -> dict[str, object]:
    observation: dict[str, object] = {
        "schema_version": "typed_progress_observation_v0",
        "result_class": "blocked",
        "work_item_id": WORK_ITEM_ID,
        "blocker_id": "blocker_owner_gate",
        "evidence_ids": ["evidence_owner_gate"],
    }
    observation.update(overrides)
    return observation


@pytest.mark.parametrize(
    "delivery_outcome, observation",
    [
        ("outcome_progress", None),
        ("primary_goal_outcome", None),
        ("outcome_gap", _blocked_observation()),
    ],
)
def test_qualifying_settlements_owe_no_diagnosis(delivery_outcome, observation):
    assert qualifies_turn_scoped_settlement(
        delivery_outcome, observation, work_item_id=WORK_ITEM_ID
    )
    assert (
        explain_turn_scoped_settlement_gap(
            delivery_outcome, observation, work_item_id=WORK_ITEM_ID
        )
        is None
    )


@pytest.mark.parametrize(
    "delivery_outcome, observation, expected",
    [
        (None, None, "--delivery-outcome is required"),
        ("surface_only", None, "--delivery-outcome surface_only cannot settle a Turn"),
        ("outcome_gap", None, "--progress-result-class blocked"),
        (
            "outcome_gap",
            _blocked_observation(result_class="advanced"),
            "requires --progress-result-class blocked; result_class=advanced",
        ),
        (
            "outcome_gap",
            _blocked_observation(blocker_id=None),
            "--progress-blocker-id",
        ),
        (
            "outcome_gap",
            _blocked_observation(evidence_ids=[]),
            "--progress-evidence-id",
        ),
        (
            "outcome_gap",
            _blocked_observation(work_item_id="todo_somewhere_else"),
            "the blocked observation must carry the settlement work item",
        ),
    ],
)
def test_gap_diagnosis_names_the_missing_or_wrong_input(
    delivery_outcome, observation, expected
):
    message = explain_turn_scoped_settlement_gap(
        delivery_outcome, observation, work_item_id=WORK_ITEM_ID
    )
    assert message is not None
    assert expected in message


def test_gap_diagnosis_names_the_ambiguous_settlement_identity():
    message = explain_turn_scoped_settlement_gap(
        "outcome_gap",
        _blocked_observation(),
        work_item_id=WORK_ITEM_ID,
        replan_obligation_id="replan-owed-settlement",
    )
    assert message is not None
    assert "--todo-id or --replan-obligation-id" in message


def _settlement_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    project = tmp_path / "project"
    state = project / ".codex" / "goals" / GOAL_ID / "ACTIVE_GOAL_STATE.md"
    state.parent.mkdir(parents=True)
    state.write_text("# Active Goal State\n\n## Agent Todo\n", encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": GOAL_ID,
                        "status": "active",
                        "repo": str(project),
                        "state_file": str(state.relative_to(project)),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    runtime_root = tmp_path / "runtime"
    runs_index = runtime_root / "goals" / GOAL_ID / "runs" / "index.jsonl"
    runs_index.parent.mkdir(parents=True)
    runs_index.write_text("", encoding="utf-8")
    return registry_path, project, runtime_root, runs_index


def test_workspace_path_refusal_names_the_missing_result_class_before_io(tmp_path):
    with pytest.raises(ValueError) as excinfo:
        refresh_state_run(
            registry_path=tmp_path / "absent-registry.json",
            runtime_root_override=None,
            goal_id=GOAL_ID,
            project=None,
            state_file=None,
            classification="validated_progress",
            recommended_action=None,
            dry_run=False,
            delivery_outcome="outcome_gap",
            delivery_workspace_path=tmp_path / "workspace",
            todo_id=WORK_ITEM_ID,
            progress_observation=_blocked_observation(result_class="advanced"),
        )
    message = str(excinfo.value)
    assert "--delivery-workspace-path requires" in message
    assert "--progress-result-class blocked" in message
    assert list(tmp_path.iterdir()) == []


def test_turn_scoped_refusal_names_the_missing_result_class_and_appends_nothing(tmp_path):
    registry_path, project, runtime_root, runs_index = _settlement_fixture(tmp_path)
    with pytest.raises(ValueError) as excinfo:
        refresh_state_run(
            registry_path=registry_path,
            runtime_root_override=str(runtime_root),
            goal_id=GOAL_ID,
            project=project,
            state_file=None,
            classification="validated_progress",
            recommended_action=None,
            dry_run=False,
            sync_global=False,
            delivery_outcome="outcome_gap",
            todo_id=WORK_ITEM_ID,
            turn_instance_id=TURN_INSTANCE_ID,
            progress_observation=_blocked_observation(result_class="advanced"),
        )
    message = str(excinfo.value)
    assert "turn-scoped refresh-state requires" in message
    assert "--progress-result-class blocked" in message
    assert runs_index.read_text(encoding="utf-8") == ""
