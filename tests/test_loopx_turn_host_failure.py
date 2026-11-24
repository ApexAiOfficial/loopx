from __future__ import annotations

import pytest

from loopx.control_plane.turn_driver.host_failure import (
    build_host_failure_record,
    host_failure_retry_available,
    normalize_host_failure_record,
    project_host_failure,
    record_host_failure,
)


@pytest.mark.parametrize(
    ("kind", "base_backoff_seconds"),
    [
        ("provider_capacity", 30),
        ("provider_overloaded", 30),
        ("rate_limited", 60),
    ],
)
def test_transient_provider_failure_uses_bounded_exponential_backoff(
    kind: str,
    base_backoff_seconds: int,
) -> None:
    first = build_host_failure_record(kind, attempt=1)
    second = build_host_failure_record(kind, attempt=2)
    exhausted = build_host_failure_record(kind, attempt=3)

    assert first["retry"] == {
        "strategy": "same_configuration",
        "max_attempts": 3,
        "backoff_seconds": base_backoff_seconds,
    }
    assert second["retry"]["backoff_seconds"] == base_backoff_seconds * 2
    assert host_failure_retry_available(first) is True
    assert host_failure_retry_available(exhausted) is False


def test_host_failure_record_rejects_caller_authored_retry_policy() -> None:
    forged = build_host_failure_record("provider_capacity", attempt=1)
    forged["retry"]["max_attempts"] = 99

    with pytest.raises(ValueError, match="invalid retry policy"):
        normalize_host_failure_record(forged)


def test_non_retryable_failure_has_no_automatic_retry_policy() -> None:
    failure = build_host_failure_record("auth_failed", attempt=1)

    assert failure == {
        "schema_version": "loopx_turn_host_failure_v0",
        "kind": "auth_failed",
        "attempt": 1,
        "retryable": False,
    }
    assert host_failure_retry_available(failure) is False


def test_exhausted_quota_requires_repair_instead_of_timed_retry() -> None:
    failure = build_host_failure_record("quota_exhausted", attempt=1)

    assert failure["retryable"] is False
    assert "retry" not in failure
    assert host_failure_retry_available(failure) is False


def test_output_budget_exhaustion_cannot_blindly_retry() -> None:
    failure = build_host_failure_record("output_budget_exhausted", attempt=1)

    assert failure["retryable"] is False
    assert "retry" not in failure
    assert host_failure_retry_available(failure) is False


def test_public_projection_rejects_unallowlisted_failure_fields() -> None:
    failure = build_host_failure_record("provider_capacity", attempt=1)
    failure["provider_message"] = "private provider prose"

    with pytest.raises(ValueError, match="unsupported fields"):
        project_host_failure({"host_failure": failure})


def test_rate_limited_backoff_stops_growing_at_the_ceiling() -> None:
    third = build_host_failure_record("rate_limited", attempt=3)
    fourth = build_host_failure_record("rate_limited", attempt=4)
    tenth = build_host_failure_record("rate_limited", attempt=10)

    assert third["retry"]["backoff_seconds"] == 240
    assert fourth["retry"]["backoff_seconds"] == 300
    assert tenth["retry"]["backoff_seconds"] == 300
    assert host_failure_retry_available(fourth) is False


def test_executor_timeout_is_the_two_attempt_policy() -> None:
    first = build_host_failure_record("executor_timeout", attempt=1)
    second = build_host_failure_record("executor_timeout", attempt=2)

    assert first["retry"] == {
        "strategy": "same_configuration",
        "max_attempts": 2,
        "backoff_seconds": 5,
    }
    assert second["retry"]["backoff_seconds"] == 10
    assert host_failure_retry_available(first) is True
    assert host_failure_retry_available(second) is False


def test_transport_lost_wakes_once_per_doubled_interval_until_exhausted() -> None:
    ladder = [
        build_host_failure_record("transport_lost", attempt=attempt)
        for attempt in (1, 2, 3)
    ]

    assert [record["retry"]["backoff_seconds"] for record in ladder] == [10, 20, 40]
    assert [host_failure_retry_available(record) for record in ladder] == [
        True,
        True,
        False,
    ]


def test_executor_journal_records_the_capped_hint_for_the_current_attempt() -> None:
    journal = {"host_attempt_count": 7}

    record_host_failure(journal, kind="rate_limited")

    assert journal["host_failure"] == build_host_failure_record(
        "rate_limited",
        attempt=7,
    )
    assert journal["host_failure"]["retry"]["backoff_seconds"] == 300


def test_normalization_returns_one_rebuilt_record_the_caller_cannot_reach() -> None:
    record = build_host_failure_record("rate_limited", attempt=2)

    normalized = normalize_host_failure_record(record)
    record["attempt"] = 99
    record["retry"]["backoff_seconds"] = 1

    assert normalized == build_host_failure_record("rate_limited", attempt=2)
    assert normalized["retry"] is not record["retry"]
    assert set(normalized) == {
        "schema_version",
        "kind",
        "attempt",
        "retryable",
        "retry",
    }


def test_projection_carries_no_hint_when_the_journal_recorded_no_failure() -> None:
    assert project_host_failure({}) == {}
    assert project_host_failure({"host_failure": "transport died"}) == {}


@pytest.mark.parametrize("attempt", [0, -1, True, "1", 1.0])
def test_attempt_must_be_a_plain_positive_integer(attempt: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        build_host_failure_record("rate_limited", attempt=attempt)  # type: ignore[arg-type]


def test_a_non_retryable_record_cannot_carry_or_claim_a_retry_policy() -> None:
    claimed = build_host_failure_record("auth_failed", attempt=1)
    claimed["retryable"] = True

    with pytest.raises(ValueError, match="retryability does not match its kind"):
        normalize_host_failure_record(claimed)

    carried = build_host_failure_record("auth_failed", attempt=1)
    carried["retry"] = build_host_failure_record("rate_limited", attempt=1)["retry"]

    with pytest.raises(ValueError, match="must not declare retry policy"):
        normalize_host_failure_record(carried)
