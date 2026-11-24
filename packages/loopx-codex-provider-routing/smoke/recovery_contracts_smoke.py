"""Focused negative-path smoke for provider runtime recovery contracts."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

contract = importlib.import_module("loopx_codex_provider_routing.contract")
qualify_desktop_patch = contract.qualify_desktop_patch
qualify_outage_recovery = contract.qualify_outage_recovery
qualify_quota_recovery = contract.qualify_quota_recovery
qualify_tool_transport = contract.qualify_tool_transport
qualify_stream_recovery = importlib.import_module(
    "loopx_codex_provider_routing.stream_recovery"
).qualify_stream_recovery


def check_stream_recovery() -> None:
    request = json.loads((PACKAGE_ROOT / "examples/stream-recovery.json").read_text())
    observation = request["stream_recovery"]
    assert qualify_stream_recovery(observation)["qualified"] is True

    # More retries cannot repair a deadline that still interrupts each attempt.
    retries_only = dict(
        observation, effective_idle_timeout_ms=300000, effective_stream_max_retries=10
    )
    result = qualify_stream_recovery(retries_only)
    assert set(result["failure_codes"]) == {
        "idle_budget_not_repaired",
        "stream_retry_budget_expanded",
    }
    # Equality leaves a race with the timeout; require headroom over the gap.
    boundary = dict(observation, effective_idle_timeout_ms=320000)
    assert qualify_stream_recovery(boundary)["qualified"] is False
    unexplained = dict(observation, observed_idle_gap_ms=299999)
    assert qualify_stream_recovery(unexplained)["failure_codes"] == [
        "idle_timeout_cause_unverified"
    ]
    # A 200, synthetic completion or a fresh session cannot prove restoration.
    for field in (
        "events_forwarded_incrementally",
        "same_session",
        "same_home",
        "history_preserved",
        "text_response_completed",
        "tool_round_trip_completed",
        "settings_readback_matches",
    ):
        failed = qualify_stream_recovery(dict(observation, **{field: False}))
        assert failed["failure_codes"] == [f"{field}_unverified"]
    for source in ("adapter", "missing"):
        failed = qualify_stream_recovery(
            dict(observation, terminal_event_source=source)
        )
        assert failed["failure_codes"] == ["upstream_completion_unverified"]

    for patch in (
        {"failure_kind": "transport_error"},
        {"failure_kind": "retry_exhausted"},
        {"previous_idle_timeout_ms": True},
        {"effective_idle_timeout_ms": 0},
        {"effective_stream_max_retries": -1},
        {"same_home": "true"},
        {"terminal_event_source": []},
        {"raw_body": "not permitted"},
        {"session_id": "not permitted"},
    ):
        try:
            qualify_stream_recovery(dict(observation, **patch))
        except (ValueError, TypeError):
            pass
        else:
            raise AssertionError(f"invalid stream observation accepted: {list(patch)}")
    missing = dict(observation)
    del missing["same_home"]
    try:
        qualify_stream_recovery(missing)
    except ValueError:
        pass
    else:
        raise AssertionError("missing session ownership proof accepted")

    # Exercise the production stdin/stdout entrypoint, including negative evidence.
    for payload, expected in (
        (request, True),
        (dict(request, stream_recovery=retries_only), False),
    ):
        run = subprocess.run(
            [sys.executable, "-m", "loopx_codex_provider_routing.cli"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=True,
            env=dict(os.environ, PYTHONPATH=str(PACKAGE_ROOT / "src")),
        )
        response = json.loads(run.stdout)
        assert response["ok"] is True
        assert response["result"]["qualified"] is expected


def main() -> int:
    check_stream_recovery()
    desktop_patch = qualify_desktop_patch(
        {
            "anchor_state": "patched_unique",
            "changed_file_count": 2,
            "per_file_integrity_match_count": 2,
            "header_integrity_matches_bundle_metadata": True,
            "signature_valid": True,
            "launch_succeeded": True,
            "heartbeat_readback_succeeded": True,
        }
    )
    assert desktop_patch["qualified"] is True

    stale_asar = qualify_desktop_patch(
        {
            "anchor_state": "unsupported",
            "changed_file_count": 2,
            "per_file_integrity_match_count": 0,
            "header_integrity_matches_bundle_metadata": False,
            "signature_valid": True,
            "launch_succeeded": False,
            "heartbeat_readback_succeeded": False,
        }
    )
    assert stale_asar["qualified"] is False
    assert {
        "desktop_patch_anchor_unsupported",
        "asar_file_integrity_stale",
        "asar_header_integrity_stale",
        "desktop_launch_failed",
        "heartbeat_transport_readback_failed",
    } <= set(stale_asar["failure_codes"])

    outage_recovery = qualify_outage_recovery(
        {
            "outage_ended": True,
            "outage_ended_observed_at": "2026-09-03T16:00:00Z",
            "cooldown_source_observed_at": "2026-09-03T14:50:00Z",
            "cooldown_expires_at": "2026-09-03T18:50:00Z",
            "cooldown_invalidated": True,
            "post_recovery_probe": "success",
            "degraded_fallback_binding_cleared": True,
            "native_capability_requested": True,
            "fallback_attempted": False,
        }
    )
    assert outage_recovery["qualified"] is True
    assert outage_recovery["expected_action"] == (
        "invalidate_cooldown_and_revalidate_affinity"
    )

    stale_outage_state = qualify_outage_recovery(
        {
            "outage_ended": True,
            "outage_ended_observed_at": "2026-09-03T16:00:00Z",
            "cooldown_source_observed_at": "2026-09-03T14:50:00Z",
            "cooldown_expires_at": "2026-09-03T18:50:00Z",
            "cooldown_invalidated": False,
            "post_recovery_probe": "not_attempted",
            "degraded_fallback_binding_cleared": False,
            "native_capability_requested": True,
            "fallback_attempted": True,
        }
    )
    assert stale_outage_state["qualified"] is False
    assert set(stale_outage_state["failure_codes"]) == {
        "stale_outage_cooldown_retained",
        "recovery_probe_missing",
        "fallback_selected_after_recovery_probe",
        "degraded_fallback_binding_used_for_native_request",
    }

    ongoing_outage_native_fallback = qualify_outage_recovery(
        {
            "outage_ended": False,
            "outage_ended_observed_at": None,
            "cooldown_source_observed_at": "2026-09-03T14:50:00Z",
            "cooldown_expires_at": "2026-09-03T18:50:00Z",
            "cooldown_invalidated": False,
            "post_recovery_probe": "not_attempted",
            "degraded_fallback_binding_cleared": False,
            "native_capability_requested": True,
            "fallback_attempted": True,
        }
    )
    assert ongoing_outage_native_fallback["qualified"] is False
    assert ongoing_outage_native_fallback["failure_codes"] == [
        "degraded_fallback_binding_used_for_native_request"
    ]

    quota_recovery = qualify_quota_recovery(
        {
            "reset_outcome": "applied",
            "reset_observed_at": "2026-09-01T11:00:00Z",
            "cooldown_source_observed_at": "2026-09-01T10:00:00Z",
            "cooldown_expires_at": "2026-09-05T10:00:00Z",
            "cooldown_invalidated": True,
            "post_reset_probe": "success",
            "fallback_attempted": False,
        }
    )
    assert quota_recovery["qualified"] is True
    assert quota_recovery["expected_action"] == "invalidate_and_probe"

    stale_cooldown = qualify_quota_recovery(
        {
            "reset_outcome": "applied",
            "reset_observed_at": "2026-09-01T11:00:00Z",
            "cooldown_source_observed_at": "2026-09-01T10:00:00Z",
            "cooldown_expires_at": "2026-09-05T10:00:00Z",
            "cooldown_invalidated": False,
            "post_reset_probe": "not_attempted",
            "fallback_attempted": True,
        }
    )
    assert stale_cooldown["qualified"] is False
    assert set(stale_cooldown["failure_codes"]) == {
        "stale_quota_cooldown_retained",
        "post_reset_probe_missing",
        "fallback_selected_before_recovered_account_probe",
    }

    tool_transport = qualify_tool_transport(
        {
            "requested_transport": "custom_tool_call",
            "observed_transport": "custom_tool_call",
            "dispatch_outcome": "completed",
        }
    )
    assert tool_transport["qualified"] is True

    downgraded_tool = qualify_tool_transport(
        {
            "requested_transport": "custom_tool_call",
            "observed_transport": "function_call",
            "dispatch_outcome": "rejected_incompatible_payload",
        }
    )
    assert downgraded_tool["qualified"] is False
    assert downgraded_tool["responsible_layer"] == "provider_response_adapter"
    assert set(downgraded_tool["failure_codes"]) == {
        "tool_transport_downgraded",
        "tool_dispatch_incomplete",
    }

    print("ok: provider recovery contracts smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
