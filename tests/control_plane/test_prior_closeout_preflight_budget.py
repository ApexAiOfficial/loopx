"""The Turn-closeout preflight must fit the latency it declares."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import loopx.control_plane.effect_runtime as effect_runtime
import loopx.control_plane.quota.unsettled_host_turn as unsettled_host_turn
from loopx.cli_commands.quota_failure_report import quota_failure_payload
from loopx.control_plane.effect_runtime import (
    EffectRuntimeRejected,
    EffectRuntimeResponseAmbiguous,
    EffectRuntimeStartupError,
)
from loopx.control_plane.quota.error_codes import CloseoutQueryUnavailableError
from loopx.control_plane.quota.unsettled_host_turn import (
    PRIOR_HOST_TURN_CLOSEOUT_PREFLIGHT_METHOD,
    PRIOR_HOST_TURN_CLOSEOUT_PREFLIGHT_REQUEST_SCHEMA,
    PRIOR_HOST_TURN_CLOSEOUT_PREFLIGHT_RESULT_SCHEMA,
    PRIOR_HOST_TURN_CLOSEOUT_PREFLIGHT_TIMEOUT_SECONDS,
    _prior_closeout_preflight,
)

DEVICE_ROOT = Path("/tmp/loopx-preflight-budget-fixture")


def _preflight(**overrides):
    kwargs = {
        "runtime_root": DEVICE_ROOT,
        "goal_id": "goal-fixture",
        "agent_id": "agent-fixture",
        "current_turn_instance_id": "turn-fixture",
    }
    kwargs.update(overrides)
    return _prior_closeout_preflight(**kwargs)


def test_the_closeout_preflight_stays_on_the_default_runtime_budget():
    """A shared indexed snapshot must not need a special timeout exemption."""

    seen: dict[str, object] = {}

    def fake_runtime(method, params, **kwargs):
        seen["method"] = method
        seen["params"] = params
        seen.update(kwargs)
        return {
            "schema_version": PRIOR_HOST_TURN_CLOSEOUT_PREFLIGHT_RESULT_SCHEMA,
            "status": "none",
        }

    with patch.object(unsettled_host_turn, "effect_runtime_result", fake_runtime):
        assert _preflight() is None

    assert seen["method"] == PRIOR_HOST_TURN_CLOSEOUT_PREFLIGHT_METHOD
    assert seen["params"]["schema_version"] == (
        PRIOR_HOST_TURN_CLOSEOUT_PREFLIGHT_REQUEST_SCHEMA
    )
    assert seen["params"]["runtime_root"] == str(DEVICE_ROOT)
    assert seen["timeout"] == PRIOR_HOST_TURN_CLOSEOUT_PREFLIGHT_TIMEOUT_SECONDS
    assert PRIOR_HOST_TURN_CLOSEOUT_PREFLIGHT_TIMEOUT_SECONDS == 5.0


def test_the_identity_conflict_diagnostic_keeps_its_typed_error():
    def rejected(method, params, **kwargs):
        raise EffectRuntimeRejected(
            "heartbeat receipt settlement identity conflicts with the current "
            "selected Todo",
            diagnostic_code="heartbeat_receipt_identity_conflict",
        )

    with patch.object(unsettled_host_turn, "effect_runtime_result", rejected):
        with pytest.raises(Exception) as raised:
            _preflight()

    assert type(raised.value).__name__ == "HeartbeatReceiptIdentityConflictError"


def test_a_lost_preflight_response_is_an_unknown_query_not_an_ambiguous_write():
    with patch.object(
        unsettled_host_turn, "effect_runtime_result",
        side_effect=EffectRuntimeResponseAmbiguous(
            PRIOR_HOST_TURN_CLOSEOUT_PREFLIGHT_METHOD, timeout=5,
        ),
    ) as request:
        with pytest.raises(CloseoutQueryUnavailableError) as raised:
            _preflight()
    assert request.call_count == 1
    assert raised.value.diagnostic_code == "closeout_query_unavailable"
    assert "closeout state is unknown" in str(raised.value)
    assert "may have committed" not in str(raised.value)
    assert isinstance(raised.value.__cause__, EffectRuntimeResponseAmbiguous)


def test_native_preflight_carries_monitor_evidence_through_python_adapter(tmp_path):
    """Real files and RPC; Python only supplies the exact current Todo fact."""
    goal, agent, turn, todo = "goal-fixture", "agent-fixture", "old-turn", "todo_monitor"
    goal_root = tmp_path / "goals" / goal
    (goal_root / "runs").mkdir(parents=True)
    (goal_root / "rollout-event-log.jsonl").write_text(json.dumps({
        "schema_version": "loopx_rollout_event_v0", "event_kind": "quota_should_run",
        "goal_id": goal, "agent_id": agent, "run_id": turn,
        "details": {"closeout_required": True, "todo_id": todo},
    }) + "\n", encoding="utf-8")
    (goal_root / "runs" / "index.jsonl").write_text(json.dumps({
        "classification": "quota_monitor_poll", "goal_id": goal, "agent_id": agent,
        "turn_instance_id": turn, "todo_id": todo,
        "quota_monitor_poll_commit": {
            "effect_id": f"quota-monitor-poll:{goal}:{agent}:{turn}:todo:{todo}",
        },
    }) + "\n", encoding="utf-8")
    with (
        patch.object(unsettled_host_turn, "_bound_todo_item", return_value={
            "todo_id": todo, "task_class": "continuous_monitor", "status": "open",
        }),
        patch(
            "loopx.control_plane.quota.monitor_poll.find_quota_monitor_poll_turn",
            side_effect=AssertionError("Python must not scan the run log again"),
        ),
    ):
        assert unsettled_host_turn._unsettled_host_turn_recovery(
            registry_path=tmp_path / "registry.json", runtime_root=tmp_path,
            goal_id=goal, agent_id=agent, current_turn_instance_id="new-turn",
        ) is None


def test_a_runtime_timeout_names_the_method_and_the_budget():
    """A caller cannot repair "request failed"; it can repair a budget."""

    with (
        patch.object(effect_runtime, "_read_info", lambda path, fingerprint: {"host": "127.0.0.1", "port": 1, "token": "x"}),
        patch.object(
            effect_runtime,
            "_request_with_info",
            side_effect=TimeoutError("timed out"),
        ),
    ):
        with pytest.raises(EffectRuntimeStartupError) as raised:
            effect_runtime.effect_runtime_request(
                "quota.fixture.method", {}, timeout=7.5
            )

    assert raised.value.diagnostic_code == "runtime_request_timeout"
    assert "quota.fixture.method" in str(raised.value)
    assert "7.5" in str(raised.value)


def test_the_quota_failure_payload_publishes_the_runtime_cause():
    args = argparse.Namespace(
        quota_command="should-run", goal_id="goal-fixture", verbose=False
    )
    error = EffectRuntimeStartupError(
        "TypeScript Effect runtime did not answer quota.fixture.method within 5s",
        diagnostic_code="runtime_request_timeout",
    )

    payload = quota_failure_payload(
        args,
        registry_path=Path("/tmp/registry.json"),
        runtime_root_arg=None,
        error=error,
    )

    assert payload["status"] == "quota_collection_failed"
    assert payload["reason"] == str(error)
    assert payload["error_code"] == "quota_unexpected_collection_error"
