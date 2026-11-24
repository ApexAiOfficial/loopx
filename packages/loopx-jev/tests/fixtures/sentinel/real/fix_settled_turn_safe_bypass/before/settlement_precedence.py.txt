from __future__ import annotations
from .effective_action import EffectiveAction

from typing import Any



HEARTBEAT_SETTLED_REPLAY_REASON = (
    "the receipt-bound work binding and required settlement receipts "
    "are complete for this heartbeat turn; defer successor selection to a new turn"
)

_ACTION_PROJECTION_KEYS = (
    "agent_command",
    "action_portfolio",
    "agent_lane_frontier_hint",
    "agent_lane_next_action",
    "agent_scope_frontier",
    "autonomous_replan_decision",
    "autonomous_replan_obligation",
    "autonomous_replan_scope",
    "blocked_priority_fallback",
    "capability_gate",
    "capability_monitor_fallback",
    "external_evidence_observation",
    "goal_route_hint",
    "notify_user_on_capability_gate",
    "notify_user_on_gate",
    "notify_user_on_open_todo",
    "open_todo_notification_policy",
    "open_todo_notify_reason",
    "required_reads",
    "replan_action_packet",
    "scoped_user_gate_fallback",
    "stall_self_repair",
    "vision_continuation_audit",
    "vision_wait_state",
    "workspace_guard",
)


def clear_quota_action_projections(
    payload: dict[str, Any],
    *,
    additional_keys: tuple[str, ...] = (),
) -> None:
    for key in (*_ACTION_PROJECTION_KEYS, *additional_keys):
        payload.pop(key, None)


def settled_replay_fields() -> dict[str, Any]:
    """Construct the authority fields of a verified, already-settled Turn."""
    reason = HEARTBEAT_SETTLED_REPLAY_REASON
    return {
        "decision": "skip",
        "should_run": False,
        "normal_delivery_allowed": False,
        "recovery_delivery_allowed": False,
        "self_repair_allowed": False,
        "capability_repair_allowed": False,
        "workspace_repair_allowed": False,
        "effective_action": EffectiveAction.HEARTBEAT_SETTLED_SKIP.value,
        "actionable_by_codex": False,
        "reason": reason,
        "requires_user_action": False,
        "recommended_action": (
            "Finish this heartbeat without another action; use a fresh turn "
            "identity for successor selection."
        ),
        "heartbeat_recommendation": {
            "recommended_mode": "heartbeat_settled_skip",
            "notify": "DONT_NOTIFY",
            "reason": reason,
            "spend_policy": "no quota spend for an already-settled heartbeat turn",
            "agent_must_attempt": False,
        },
        "execution_obligation": {
            "must_attempt_work": False,
            "kind": "heartbeat_settled_skip",
            "delivery_allowed": False,
            "notify_is_execution_gate": False,
            "reason": reason,
            "spend_policy": "no quota spend for an already-settled heartbeat turn",
        },
    }
