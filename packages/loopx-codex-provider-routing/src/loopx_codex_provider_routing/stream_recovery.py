"""Content-free qualification of SSE idle-timeout recovery in the same session."""

from collections.abc import Mapping
from typing import Any

from .contract import reject_private_material


def qualify_stream_recovery(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Reject retry-only fixes, buffered streams and replacement-session probes.

    This qualifies an observed idle timeout, not the provider's internal cause
    or an arbitrary network failure. Effects and raw evidence stay with the
    operator and provider transport.
    """
    reject_private_material(observation)
    integers = {
        "previous_idle_timeout_ms": 1,
        "effective_idle_timeout_ms": 1,
        "observed_idle_gap_ms": 1,
        "previous_stream_max_retries": 0,
        "effective_stream_max_retries": 0,
    }
    booleans = {
        "events_forwarded_incrementally",
        "same_session",
        "same_home",
        "history_preserved",
        "text_response_completed",
        "tool_round_trip_completed",
        "settings_readback_matches",
    }
    fields = set(integers) | booleans | {"failure_kind", "terminal_event_source"}
    if set(observation) != fields:
        raise ValueError("stream_recovery has missing or unsupported fields")
    if observation["failure_kind"] != "sse_idle_timeout":
        raise ValueError("stream_recovery requires an observed sse_idle_timeout")
    for key, minimum in integers.items():
        if type(observation[key]) is not int or observation[key] < minimum:
            raise TypeError(f"stream_recovery.{key} requires an integer >= {minimum}")
    for key in booleans:
        if type(observation[key]) is not bool:
            raise TypeError(f"stream_recovery.{key} requires a boolean")
    source = observation["terminal_event_source"]
    if source not in ("upstream", "adapter", "missing"):
        raise ValueError("stream_recovery.terminal_event_source is unsupported")

    before = observation["previous_idle_timeout_ms"]
    after = observation["effective_idle_timeout_ms"]
    gap = observation["observed_idle_gap_ms"]
    checks = [
        {
            "id": "idle_deadline_explains_failure",
            "passed": gap >= before,
            "failure_code": "idle_timeout_cause_unverified",
        },
        {
            "id": "idle_budget_covers_observed_gap",
            "passed": after > gap,
            "failure_code": "idle_budget_not_repaired",
        },
        {
            "id": "retry_budget_not_expanded",
            "passed": observation["effective_stream_max_retries"]
            <= observation["previous_stream_max_retries"],
            "failure_code": "stream_retry_budget_expanded",
        },
        {
            "id": "upstream_completion",
            "passed": source == "upstream",
            "failure_code": "upstream_completion_unverified",
        },
    ]
    checks.extend(
        {"id": key, "passed": observation[key], "failure_code": f"{key}_unverified"}
        for key in sorted(booleans)
    )
    failures = [row["failure_code"] for row in checks if not row["passed"]]
    return {
        "schema_version": "codex_stream_recovery_qualification_v0",
        "qualified": not failures,
        "failure_codes": failures,
        "checks": checks,
        "responsible_layer": "provider_stream_transport",
        "effect_boundary": "content_free_observation_only",
        "required_contract": {
            "idle_timeout_setting": "stream_idle_timeout_ms",
            "retry_setting": "stream_max_retries",
            "retry_only_repair": False,
            "completion_must_come_from_upstream": True,
            "session_store_mutation": "none",
            "provider_internal_cause": "unverified",
        },
    }
