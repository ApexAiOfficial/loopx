"""Real Todo facade observation, immutable retry and lifecycle readback."""
from dataclasses import replace

import pytest

from canonical_authority_fixture import isolate_sqlite_runtime
from test_native_monitor_poll import _canonical, GOAL_ID, AGENT_ID
from loopx.control_plane.coordination.local_authority import read_canonical_todos_if_promoted
from loopx.control_plane.todos.monitor_metadata import MonitorPollObservation
from loopx.todos import update_goal_todo, complete_goal_todo


@pytest.mark.parametrize("provider", ["file", "sqlite"])
@pytest.mark.parametrize("native", [False, True])
def test_observation_completion_replay_and_same_hash_reactivation(tmp_path, monkeypatch, provider, native):
    isolate_sqlite_runtime(tmp_path, monkeypatch)
    registry, runtime, state, monitor = _canonical(tmp_path, native=native, provider=provider)
    state.unlink()
    arguments = dict(registry_path=registry, runtime_root_arg=str(runtime), goal_id=GOAL_ID,
        todo_id=monitor["todo_id"], agent_id=AGENT_ID, role="agent")
    observation = MonitorPollObservation(generated_at="2030-01-01T00:00:00Z",
        result_hash="same-member-set", material_change=True, monitor_effect_id="observe-first", cadence="1h")
    first = update_goal_todo(**arguments, monitor_metadata=observation)
    assert first["status"] == "applied"
    assert first["monitor_poll_transition"]["material_change_generation"] == 1
    assert first["projection_delivery"] == "delivered"
    completed = complete_goal_todo(**arguments, no_followup=True)
    assert completed["changed"] is True
    before = read_canonical_todos_if_promoted(runtime_root=runtime, goal_id=GOAL_ID)
    replay = update_goal_todo(**arguments, monitor_metadata=observation)
    assert replay["status"] == "replayed"
    assert replay["monitor_poll_transition"] == first["monitor_poll_transition"]
    assert read_canonical_todos_if_promoted(runtime_root=runtime, goal_id=GOAL_ID) == before
    revived = update_goal_todo(**arguments, status="open", no_followup=False,
        monitor_metadata=replace(observation, generated_at="2031-01-01T00:00:00Z", monitor_effect_id="observe-new-cycle"))
    assert revived["status"] == "applied"
    assert revived["monitor_poll_transition"]["material_change_generation"] == 2
    current = read_canonical_todos_if_promoted(runtime_root=runtime, goal_id=GOAL_ID)
    row = next(todo for todo in current["todos"] if todo["todo_id"] == monitor["todo_id"])
    assert row["status"] == "open" and row["done"] is False
    assert row["result_hash"] == "same-member-set"
    assert "completed_at" not in row and "completion_continuation" not in row
    assert revived["projection_delivery"] in {"delivered", "current"}
    completed_again = complete_goal_todo(**arguments, no_followup=True)
    assert completed_again["provider_status"] == "applied"
    assert completed_again["changed"] is True
    assert (
        completed_again["original_receipt"]["operation_id"]
        != completed["original_receipt"]["operation_id"]
    )
    final = read_canonical_todos_if_promoted(runtime_root=runtime, goal_id=GOAL_ID)
    row = next(todo for todo in final["todos"] if todo["todo_id"] == monitor["todo_id"])
    assert row["status"] == "done" and row["done"] is True
    second_replay = complete_goal_todo(**arguments, no_followup=True)
    assert second_replay["provider_status"] == "replayed"
    assert second_replay["original_receipt"] == completed_again["original_receipt"]


@pytest.mark.parametrize("provider", ["file", "sqlite"])
def test_observation_rejects_mixed_edits_and_unavailable_authority(tmp_path, monkeypatch, provider):
    isolate_sqlite_runtime(tmp_path, monkeypatch)
    registry, runtime, state, monitor = _canonical(tmp_path, provider=provider)
    arguments = dict(registry_path=registry, runtime_root_arg=str(runtime), goal_id=GOAL_ID,
        todo_id=monitor["todo_id"], agent_id=AGENT_ID,
        monitor_metadata=MonitorPollObservation(generated_at="2030-01-01T00:00:00Z",
            result_hash="observed", material_change=True, monitor_effect_id="rejected-observation"))
    before = read_canonical_todos_if_promoted(runtime_root=runtime, goal_id=GOAL_ID)
    display = state.read_bytes()
    for extra in ({"text": "Bundled copy"}, {"claimed_by": AGENT_ID}, {"status": "done"}):
        with pytest.raises((RuntimeError, ValueError)):
            update_goal_todo(**arguments, **extra)
        assert read_canonical_todos_if_promoted(runtime_root=runtime, goal_id=GOAL_ID) == before
        assert state.read_bytes() == display


@pytest.mark.parametrize("provider", ["file", "sqlite"])
@pytest.mark.parametrize("native", [False, True])
def test_completed_leased_monitor_reopens_then_requires_fresh_cli_execution(tmp_path, monkeypatch, provider, native):
    from loopx.control_plane.testing.canary_harness import run_json_cli
    from loopx.control_plane.coordination.local_authority import LocalCoordinationAuthorityUnavailable
    isolate_sqlite_runtime(tmp_path, monkeypatch)
    registry, runtime, state, monitor = _canonical(tmp_path, provider=provider, native=native,
        lease={"status": "active", "idempotency_key": "original-cycle", "version": 3, "lease_epoch": 2,
               "acquired_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
               "expires_at": "2099-01-01T00:00:00Z"})
    args = dict(registry_path=registry, runtime_root_arg=str(runtime), goal_id=GOAL_ID,
                todo_id=monitor["todo_id"], agent_id=AGENT_ID, role="agent")
    done = complete_goal_todo(**args, no_followup=True,
        task_lease_idempotency_key="original-cycle", task_lease_expected_version=3)
    assert done["changed"] is True
    state.unlink()
    observation = MonitorPollObservation(generated_at="2030-01-01T00:00:00Z",
        result_hash="new-cycle", material_change=True, monitor_effect_id="reopen-cycle", cadence="1h")
    reopened = update_goal_todo(**args, status="open", monitor_metadata=observation)
    assert reopened["status"] == "applied"
    assert reopened["monitor_lifecycle_transition"]["lease_retirement"] == "already_released"
    assert reopened["monitor_lifecycle_transition"]["execution_authority_granted"] is False
    assert reopened["projection_delivery"] == "delivered"
    with pytest.raises(LocalCoordinationAuthorityUnavailable):
        update_goal_todo(**args, monitor_metadata=replace(observation,
            generated_at="2030-01-01T00:01:00Z", monitor_effect_id="stale-execution"),
            task_lease_idempotency_key="original-cycle", task_lease_expected_version=3)
    acquired = run_json_cli("task-lease", "acquire", "--goal-id", GOAL_ID,
        "--todo-id", monitor["todo_id"], "--owner", AGENT_ID,
        "--idempotency-key", "fresh-cycle", "--expected-version", "3", "--ttl-seconds", "600",
        registry_path=registry, runtime_root=runtime)
    lease = acquired["lease"]
    assert lease["version"] == 4 and lease["lease_epoch"] == 3
    replay = update_goal_todo(**args, status="open", monitor_metadata=observation)
    assert replay["status"] == "replayed"
    observed = update_goal_todo(**args, monitor_metadata=replace(observation,
        generated_at="2030-01-01T00:02:00Z", monitor_effect_id="fresh-observation", result_hash="changed"),
        task_lease_idempotency_key="fresh-cycle", task_lease_expected_version=4)
    assert observed["status"] == "applied"
    assert observed["monitor_poll_transition"]["material_change_generation"] == 2
