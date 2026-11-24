"""Settled Turns have observations, but never construct a successor action."""
from __future__ import annotations

import pytest

from loopx.control_plane.effect_program import ReceiptBoundReplayPhase
from loopx.control_plane.quota import should_run_packet
from loopx.control_plane.quota.should_run import build_quota_should_run
from loopx.control_plane.testing.quota_fixtures import quota_status_payload
from loopx.presentation.renderers.quota_markdown import render_quota_should_run_markdown


@pytest.mark.parametrize("quota_state", ["eligible", "operator_gate", "waiting_external", "exhausted"])
@pytest.mark.parametrize("monitor", [False, True])
def test_settled_turn_never_constructs_successor_or_replan(
    monkeypatch: pytest.MonkeyPatch, quota_state: str, monitor: bool,
) -> None:
    def unexpected(*args, **kwargs):
        pytest.fail("settled replay entered an executable action construction path")

    monkeypatch.setattr(should_run_packet, "_resolve_agent_lane_delivery_route", unexpected)
    monkeypatch.setattr(should_run_packet, "build_replan_action_packet", unexpected)
    monkeypatch.setattr(should_run_packet, "_apply_agent_monitor_only_precedence", unexpected)
    status = quota_status_payload(
        goal_id="settled-fixture", status="active", quota_state=quota_state,
        agent_todo_items=[{
            "todo_id": "todo_successor", "index": 1, "text": "[P1] Advance successor",
            "role": "agent", "status": "open", "priority": "P1",
            "task_class": "continuous_monitor" if monitor else "advancement_task",
        }],
        recommended_action="Advance successor",
    )
    payload = build_quota_should_run(
        status, goal_id="settled-fixture", available_capabilities=["shell"],
        receipt_bound_replay_phase=ReceiptBoundReplayPhase.SETTLED,
    )
    assert payload["effective_action"] == "heartbeat_settled_skip"
    assert payload["decision"] == "skip"
    for flag in (
        "should_run", "normal_delivery_allowed", "recovery_delivery_allowed",
        "self_repair_allowed", "capability_repair_allowed", "workspace_repair_allowed",
        "actionable_by_codex", "requires_user_action",
    ):
        assert payload[flag] is False, flag
    assert payload["execution_obligation"]["must_attempt_work"] is False
    assert payload["heartbeat_recommendation"]["agent_must_attempt"] is False
    for field in ("selected_todo", "replan_action_packet", "autonomous_replan_obligation", "action_portfolio"):
        assert field not in payload
    assert payload["interaction_contract"]["agent_channel"]["must_attempt"] is False
    assert payload["interaction_contract"]["cli_channel"]["spend_after_validation"] is False
    assert payload["protocol_action_packet"]["summary"]


def test_pause_still_precedes_settled_replay() -> None:
    status = quota_status_payload(
        goal_id="settled-fixture", status="active", quota_state="paused",
        recommended_action="Wait for owner",
    )
    payload = build_quota_should_run(
        status, goal_id="settled-fixture",
        receipt_bound_replay_phase=ReceiptBoundReplayPhase.SETTLED,
    )
    assert payload["should_run"] is False
    assert payload["effective_action"] == "quota_skip"
    assert payload["state"] == "paused"


def test_live_intent_can_follow_settled_quota_without_reopening_work(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace
    from loopx.control_plane.quota import live_decision
    from loopx.control_plane.capability_hooks import (
        InteractionProjectionHookRegistration,
        INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION,
    )

    # Receipt identity/refusal is covered through the real CLI settlement tests;
    # this case isolates composition with the real typed hook decoder.
    monkeypatch.setattr(live_decision, "read_heartbeat_settlement", lambda *args, **kwargs: SimpleNamespace(
        replay_phase=ReceiptBoundReplayPhase.SETTLED, monitor_phase=None,
    ))
    command = "loopx periodic-report consume-pending --goal-id settled-fixture --agent-id fixture-agent --execute"
    hook = InteractionProjectionHookRegistration(
        hook_id="periodic_report.pending_intent", capability_id="periodic-report",
        projection_slots=("pending_capability_intent",),
        requested_read_scope=("post_writeback_intent_journal",),
        producer=lambda: {
            "schema_version": INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION,
            "hook_id": "periodic_report.pending_intent", "capability_id": "periodic-report",
            "phase": "interaction_projection", "status": "candidate",
            "projection_slot": "pending_capability_intent",
            "payload": {
                "schema_version": "pending_capability_intent_projection_v0",
                "capability_id": "periodic-report", "intent_kind": "periodic_report.trigger_evaluation",
                "idempotency_key": "periodic-report:fixture", "intent_digest": "sha256:" + "a" * 64,
                "goal_id": "settled-fixture", "agent_id": "fixture-agent", "state": "pending",
                "action_kind": "consume_periodic_report_intent",
                "action_summary": "Generate the report under its own receipt.", "command": command,
                "generation_authorized": True, "external_delivery_authorized": True,
                "agent_read_required": True,
            },
        },
    )
    payload = live_decision.build_live_quota_should_run_decision(
        quota_status_payload(goal_id="settled-fixture", status="active", recommended_action="Continue"),
        goal_id="settled-fixture", agent_id=None, available_capabilities=["shell"],
        include_scheduler_detail=False, codex_app_current_rrule=None,
        registry_path=tmp_path / "registry.json", runtime_root=tmp_path / "runtime",
        interaction_projection_hooks=[hook],
    )
    assert payload["effective_action"] == "governed_capability_intent"
    assert payload["interaction_contract"]["cli_channel"]["next_cli_actions"] == [command]
    assert payload.get("selected_todo") is None
    assert payload["normal_delivery_allowed"] is False


def test_settled_fallback_readback_cannot_reopen_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    from loopx.control_plane.quota import should_run
    original = should_run._prepare_quota_should_run_item

    def prepare(*args, **kwargs):
        prepared = original(*args, **kwargs)
        prepared.scoped_user_gate_fallback = {"reason": "scoped gate", "recommended_action": "Safe work"}
        return prepared

    monkeypatch.setattr(should_run, "_prepare_quota_should_run_item", prepare)
    payload = build_quota_should_run(
        quota_status_payload(goal_id="settled-fixture", status="active", recommended_action="Continue"),
        goal_id="settled-fixture", receipt_bound_replay_phase=ReceiptBoundReplayPhase.SETTLED,
    )
    # The heartbeat task body reads safe_bypass_allowed=true under
    # should_run=false as permission to run one bounded step and spend once, so
    # a settled Turn must not inherit the fallback grant from its readback.
    assert payload["safe_bypass_allowed"] is False
    assert payload["safe_bypass_kind"] is None
    assert "safe_bypass_policy" not in payload
    assert payload["should_run"] is False
    assert payload["actionable_by_codex"] is False
    assert payload["execution_obligation"]["must_attempt_work"] is False
    assert payload["interaction_contract"]["mode"] == "heartbeat_settled_skip"
    assert payload["interaction_contract"]["agent_channel"]["must_attempt"] is False
    assert payload["interaction_contract"]["cli_channel"]["spend_after_validation"] is False
    assert "scoped_user_gate_fallback" not in payload

    recommendation = payload["heartbeat_recommendation"]
    assert recommendation["recommended_mode"] == "heartbeat_settled_skip"
    assert recommendation["agent_must_attempt"] is False
    assert "no quota spend" in recommendation["spend_policy"]

    # The guidance the agent actually reads must not carry a second, executable
    # reading of the same settled Turn.
    guidance = render_quota_should_run_markdown(payload)
    assert "safe_bypass" not in guidance
    assert "spend only after validated writeback" not in guidance
    assert "heartbeat_spend_policy: no quota spend" in guidance
