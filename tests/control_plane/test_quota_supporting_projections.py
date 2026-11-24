"""Quota diagnostics preserve observations without granting execution authority."""

from copy import deepcopy

import pytest

from loopx.control_plane.quota.should_run_packet import (
    _attach_quota_supporting_projections,
)


@pytest.mark.parametrize("should_run,notify_gate", [(True, True), (False, False)])
def test_gate_observations_do_not_reopen_settled_execution(
    should_run: bool, notify_gate: bool,
) -> None:
    payload = {"should_run": should_run}
    item = {
        "operator_question": "Approve the next step?",
        "agent_command": "loopx status",
        "stale_latest_run_warning": {"reason": "stale observation"},
        "backlog_hygiene_warning": "invalid diagnostic shape",
        "next_handoff_condition": "Owner decision arrives",
    }
    before = deepcopy(item)
    _attach_quota_supporting_projections(
        payload, status_payload={}, item=item, project_asset={},
        goal_id="projection-fixture", selected_recommended_action="Wait for approval",
        state="operator_gate", user_todo_summary=None, should_run=should_run,
        state_action_projection_warning=None, next_action_warning=None,
        replan_obligation=None, notify_gate=notify_gate,
    )
    assert payload["should_run"] is should_run
    assert payload["gate_prompt"]
    assert payload.get("notify_user_on_gate", False) is notify_gate
    assert ("agent_command" in payload) is should_run
    assert payload["stale_latest_run_warning"] == {"reason": "stale observation"}
    assert "backlog_hygiene_warning" not in payload
    assert payload["next_handoff_condition"] == "Owner decision arrives"
    assert item == before


@pytest.mark.parametrize("action,goal_id,matches", [
    ("Retry obsolete endpoint", "projection-fixture", True),
    ("Validate fresh parser", "projection-fixture", False),
    ("Retry obsolete endpoint", "other-goal", False),
    (None, "projection-fixture", False),
])
def test_reward_warning_is_scoped_to_selected_action_and_goal(
    action: str | None, goal_id: str, matches: bool,
) -> None:
    status = {"run_history": {"goals": [{
        "id": "projection-fixture",
        "latest_runs": [{"human_reward": {"lesson": {
            "summary": "Use the current endpoint", "avoid": ["obsolete endpoint"],
        }}}],
    }]}}
    payload = {}
    _attach_quota_supporting_projections(
        payload, status_payload=status, item={}, project_asset={}, goal_id=goal_id,
        selected_recommended_action=action, state="eligible", user_todo_summary=None,
        should_run=False, state_action_projection_warning=None,
        next_action_warning=None, replan_obligation=None,
    )
    assert ("reward_lesson_projection_warning" in payload) is matches
    if matches:
        warning = payload["reward_lesson_projection_warning"]
        assert warning["goal_id"] == goal_id
        assert warning["match_count"] == 1
        assert warning["matches"][0]["avoid"] == "obsolete endpoint"
    assert "agent_command" not in payload
    assert "notify_user_on_gate" not in payload
