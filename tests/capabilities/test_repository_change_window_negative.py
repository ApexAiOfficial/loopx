"""The repository change window fails closed: a locked window denies the write.

Two negative contracts are pinned here, both provider-neutral and synthetic:

1. a blocked window reports a denial with the next eligible instant, and the
   denied work is retained as an ``open`` pending change rather than dropped;
2. a pending change only leaves ``open`` through one typed terminal resolution
   (``merged`` / ``superseded`` / ``abandoned``) that is immutable afterwards.

The remaining cases pin the validation rejections that keep a malformed policy,
change id, state filter or resolution from being silently accepted.

Existing coverage for the positive paths lives in
``tests/capabilities/test_repository_change_window.py``; this module only adds
the fail-closed branches, so it intentionally reuses that module's repository
and policy helpers instead of rebuilding them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_repository_change_window import _repository, _weekday_policy

from loopx.capabilities.repository_change_window import (
    evaluate_policy,
    list_pending_changes,
    record_pending_change,
    resolve_pending_change,
    verify_pending_change,
)
from loopx.capabilities.repository_change_window.policy import (
    BlockedWindow,
    ChangeWindowPolicy,
    ChangeWindowPolicyError,
    Weekday,
    parse_local_time,
)
from loopx.capabilities.repository_change_window.repository import (
    RepositoryChangeWindowError,
)

CHANGE_ID = "change_negative_fixture_01"
OTHER_CHANGE_ID = "change_negative_fixture_02"


def _open_pending_change(repo: Path, runtime_root: Path, *, change_id: str = CHANGE_ID):
    """Record one open pending change against a blocked-window decision."""

    decision = evaluate_policy(
        _weekday_policy(),
        now=datetime.fromisoformat("2026-08-18T12:00:00+08:00"),
    )
    assert decision["allowed"] is False
    return record_pending_change(
        runtime_root=runtime_root,
        repo_path=repo,
        decision=decision,
        source="negative_fixture",
        change_id=change_id,
        pr_ref="pr/9999",
        execute=True,
    )


def test_a_blocked_window_denies_the_write_and_retains_it_as_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repository(tmp_path, monkeypatch)
    runtime_root = tmp_path / "runtime"
    recorded = _open_pending_change(repo, runtime_root)

    decision = recorded["record"]["gate_decision"]
    assert decision["allowed"] is False
    assert decision["reason"] == "inside_blocked_window"
    observed = datetime.fromisoformat(decision["observed_at"])
    eligible = datetime.fromisoformat(decision["next_eligible_at"])
    assert eligible > observed, "a denial must name an instant the write may resume"

    # The denied write is retained, not dropped: it stays open and locatable.
    assert recorded["record"]["state"] == "open"
    listed = list_pending_changes(runtime_root=runtime_root, state="open")
    assert listed["count"] == 1
    assert listed["changes"][0]["change_id"] == CHANGE_ID
    assert verify_pending_change(runtime_root=runtime_root, change_id=CHANGE_ID)["ok"]


@pytest.mark.parametrize("resolution", ["merged", "superseded", "abandoned"])
def test_open_leaves_only_through_a_typed_terminal_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resolution: str,
) -> None:
    repo = _repository(tmp_path, monkeypatch)
    runtime_root = tmp_path / "runtime"
    _open_pending_change(repo, runtime_root)

    superseded_by = OTHER_CHANGE_ID if resolution == "superseded" else None
    resolved = resolve_pending_change(
        runtime_root=runtime_root,
        change_id=CHANGE_ID,
        resolution=resolution,
        evidence="synthetic negative fixture evidence",
        superseded_by=superseded_by,
        execute=True,
    )
    assert resolved["changed"] is True
    assert resolved["duplicate"] is False

    assert list_pending_changes(runtime_root=runtime_root, state="open")["count"] == 0
    terminal = list_pending_changes(runtime_root=runtime_root, state="resolved")
    assert terminal["count"] == 1
    assert terminal["changes"][0]["resolution"] == resolution
    # A terminal row has no live locator, so it can no longer be verified open.
    assert verify_pending_change(runtime_root=runtime_root, change_id=CHANGE_ID)[
        "status"
    ] == "unlocatable"


def test_terminal_resolution_is_immutable_and_requires_its_successor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repository(tmp_path, monkeypatch)
    runtime_root = tmp_path / "runtime"
    _open_pending_change(repo, runtime_root)

    with pytest.raises(RepositoryChangeWindowError, match="requires superseded_by"):
        resolve_pending_change(
            runtime_root=runtime_root,
            change_id=CHANGE_ID,
            resolution="superseded",
            evidence="successor omitted",
            execute=True,
        )
    # The rejected attempt must not have consumed the open row.
    assert list_pending_changes(runtime_root=runtime_root, state="open")["count"] == 1

    resolve_pending_change(
        runtime_root=runtime_root,
        change_id=CHANGE_ID,
        resolution="merged",
        evidence="merge commit deadbeef",
        execute=True,
    )
    with pytest.raises(RepositoryChangeWindowError, match="different terminal"):
        resolve_pending_change(
            runtime_root=runtime_root,
            change_id=CHANGE_ID,
            resolution="abandoned",
            evidence="conflicting second resolution",
            execute=True,
        )
    replayed = resolve_pending_change(
        runtime_root=runtime_root,
        change_id=CHANGE_ID,
        resolution="merged",
        evidence="merge commit deadbeef",
        execute=True,
    )
    assert replayed["duplicate"] is True
    assert replayed["changed"] is False


def test_a_resolved_pending_change_cannot_be_reopened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repository(tmp_path, monkeypatch)
    runtime_root = tmp_path / "runtime"
    _open_pending_change(repo, runtime_root)
    resolve_pending_change(
        runtime_root=runtime_root,
        change_id=CHANGE_ID,
        resolution="merged",
        evidence="merge commit deadbeef",
        execute=True,
    )

    with pytest.raises(RepositoryChangeWindowError, match="cannot be reopened"):
        _open_pending_change(repo, runtime_root)
    assert list_pending_changes(runtime_root=runtime_root, state="open")["count"] == 0


def test_malformed_or_unknown_identifiers_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repository(tmp_path, monkeypatch)
    runtime_root = tmp_path / "runtime"
    _open_pending_change(repo, runtime_root)

    with pytest.raises(RepositoryChangeWindowError, match="invalid change_id"):
        resolve_pending_change(
            runtime_root=runtime_root,
            change_id="CHANGE-ID",
            resolution="merged",
            evidence="synthetic",
            execute=True,
        )
    with pytest.raises(RepositoryChangeWindowError, match="unknown pending change"):
        resolve_pending_change(
            runtime_root=runtime_root,
            change_id=OTHER_CHANGE_ID,
            resolution="merged",
            evidence="synthetic",
            execute=True,
        )
    with pytest.raises(RepositoryChangeWindowError, match="unknown pending change"):
        verify_pending_change(runtime_root=runtime_root, change_id=OTHER_CHANGE_ID)
    with pytest.raises(RepositoryChangeWindowError, match="resolution must be"):
        resolve_pending_change(
            runtime_root=runtime_root,
            change_id=CHANGE_ID,
            resolution="closed",
            evidence="synthetic",
            execute=True,
        )
    with pytest.raises(RepositoryChangeWindowError, match="state must be"):
        list_pending_changes(runtime_root=runtime_root, state="everything")


def test_a_policy_that_cannot_admit_a_write_is_rejected() -> None:
    with pytest.raises(ChangeWindowPolicyError, match="unknown IANA timezone"):
        ChangeWindowPolicy(
            timezone_name="Mars/Olympus",
            blocked_windows=(
                BlockedWindow(
                    weekdays=(Weekday.MONDAY,),
                    start_local=parse_local_time("10:00"),
                    end_local=parse_local_time("11:00"),
                ),
            ),
        )
    with pytest.raises(ChangeWindowPolicyError, match="must differ"):
        BlockedWindow(
            weekdays=(Weekday.MONDAY,),
            start_local=parse_local_time("10:00"),
            end_local=parse_local_time("10:00"),
        )
    with pytest.raises(ChangeWindowPolicyError, match="weekdays must be unique"):
        BlockedWindow(
            weekdays=(Weekday.MONDAY, Weekday.MONDAY),
            start_local=parse_local_time("10:00"),
            end_local=parse_local_time("11:00"),
        )
    with pytest.raises(ChangeWindowPolicyError, match="at least one weekday"):
        BlockedWindow(
            weekdays=(),
            start_local=parse_local_time("10:00"),
            end_local=parse_local_time("11:00"),
        )
    with pytest.raises(ChangeWindowPolicyError, match="minute precision"):
        parse_local_time("10:00:30")
    with pytest.raises(ChangeWindowPolicyError, match="unsupported weekday"):
        Weekday.parse("funday")
    with pytest.raises(ChangeWindowPolicyError, match="policy must use"):
        ChangeWindowPolicy.from_dict(
            {
                "schema_version": "repository_change_window_policy_v9",
                "timezone": "UTC",
                "strategy": "deny_during_local_windows",
                "blocked_windows": [
                    {"weekdays": ["mon"], "start_local": "10:00", "end_local": "11:00"}
                ],
            }
        )
    with pytest.raises(ChangeWindowPolicyError, match="strategy must be"):
        ChangeWindowPolicy.from_dict(
            {
                "schema_version": "repository_change_window_policy_v0",
                "timezone": "UTC",
                "strategy": "allow_during_local_windows",
                "blocked_windows": [
                    {"weekdays": ["mon"], "start_local": "10:00", "end_local": "11:00"}
                ],
            }
        )


def test_policy_evaluation_requires_an_aware_clock() -> None:
    with pytest.raises(ChangeWindowPolicyError, match="timezone-aware"):
        evaluate_policy(
            _weekday_policy(),
            now=datetime(2026, 8, 18, 12, 0),
        )
    # A UTC clock still evaluates against the policy's own local zone.
    decision = evaluate_policy(
        _weekday_policy(),
        now=datetime(2026, 8, 18, 4, 0, tzinfo=UTC),
    )
    assert decision["allowed"] is False
    assert decision["timezone"] == "Asia/Shanghai"
