"""Shadow semantics with real Git/files and injected model answers, not quality scores."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import subprocess

import pytest

from loopx_jev import drift
from loopx_jev.drift_capture import delta, stable_capture
from loopx_jev.drift_cli import refresh
from loopx_jev.store import atomic_json
from loopx_jev.transport import TransportFailure
from drift_fixtures import DRIFT_NOULS, response


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def study(tmp_path):
    repo = tmp_path / "work"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Fixture")
    (repo / "code.py").write_text("TIMEOUT = 1\n")
    git(repo, "add", "code.py")
    git(repo, "commit", "-qm", "baseline")
    basis = tmp_path / "basis.json"
    atomic_json(
        basis,
        {
            "goal_id": "drift-test",
            "objective": "Retry transient failures",
            "acceptance": ["A transient error is retried once"],
            "evidence": [],
        },
    )
    config = tmp_path / "config.json"
    atomic_json(
        config,
        {
            "schema_version": "loopx_jev_drift_config_v0",
            "mode": "shadow",
            "scenarios": ["progress_review"],
            "model": "fixture-v1",
            "allow_egress": True,
        },
    )
    root = tmp_path / "observer"
    drift.initialize(root, repo, basis, config, ["code.py", "new.txt"])
    return root, repo, basis, config


def record(study, sequence=1):
    root, repo, basis, config = study
    path = root.parent / f"run-{sequence}.json"
    atomic_json(
        path,
        {
            "goal_id": "drift-test",
            "generated_at": f"2026-01-01T00:00:{sequence:02d}Z",
            "turn_instance_id": f"turn-{sequence}",
            "agent_id": "worker",
            "todo_id": "retry",
            "progress_observation": {"outcome": "advanced"},
        },
    )
    return path


def change_and_queue(study, sequence=1):
    root, repo, basis, config = study
    (repo / "code.py").write_text(f"RENAMED_TIMEOUT = {sequence}\n")
    return drift.enqueue(root, drift.prepare(root, config), record(study, sequence))


def provider(calls):
    def send(request, config, key):
        calls.append(request)
        return {"response": response(request, ["off_goal", "no_new_evidence"], nouls=DRIFT_NOULS)}

    return send


def forbidden(*args, **kwargs):
    raise AssertionError("disabled side effect")


def test_off_is_exact_original_call_without_state_or_credential_reads(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr("loopx_jev.drift.prepare", forbidden)
    args = ["refresh-state", "--goal-id", "missing"]

    def invoke(actual):
        assert actual == args
        print("original stdout")
        return 7

    assert refresh(args, tmp_path / "missing", None, invoke) == 7
    captured = capsys.readouterr()
    assert captured.out == "original stdout\n" and captured.err == ""
    assert drift.drain(
        tmp_path / "missing", None, transport=forbidden, credential=forbidden
    ) == {"status": "disabled"}
    assert not (tmp_path / "missing").exists()


def test_read_commit_staged_unstaged_and_untracked_net_changes(study):
    root, repo, basis, config = study
    first = stable_capture(repo, ["code.py", "new.txt"])
    (repo / "code.py").write_text("TIMEOUT = 2\n")
    unstaged = stable_capture(repo, ["code.py", "new.txt"])
    git(repo, "add", "code.py")
    staged = stable_capture(repo, ["code.py", "new.txt"])
    git(repo, "commit", "-qm", "work")
    committed = stable_capture(repo, ["code.py", "new.txt"])
    assert delta(first, unstaged) == delta(first, staged) == delta(first, committed)
    (repo / "new.txt").write_text("Negative experiment: timeout still occurs\n")
    assert "Negative experiment" in delta(
        committed, stable_capture(repo, ["code.py", "new.txt"])
    )
    assert git(repo, "status", "--porcelain").strip() == "?? new.txt"


def test_real_delta_without_self_report_and_restart_dedup(study):
    root, repo, basis, config = study
    item = change_and_queue(study)
    again = drift.enqueue(root, drift.prepare(root, config), record(study))
    assert item["status"] == "queued" and again["status"] == "duplicate_event"
    calls = []
    assert (
        len(
            drift.drain(
                root, config, transport=provider(calls), credential=lambda: "fixture"
            )["processed"]
        )
        == 1
    )
    assert (
        drift.drain(root, config, transport=forbidden, credential=forbidden)[
            "processed"
        ]
        == []
    )
    assert len(calls) == 1
    text = json.dumps(calls[0])
    assert "-TIMEOUT = 1" in text and "+RENAMED_TIMEOUT = 1" in text
    assert "progress_observation" not in text and "turn_instance_id" not in text
    report = drift.status(root)
    assert report["authority"] == "none" and report["observer_influence"] == "none"
    assert report["core_consumption"] == "goal_progress_review_policy"
    assert report["events"][0]["judgments"]["relation"] == "off_goal"
    assert not list((root / "jobs").iterdir())


def test_same_delta_never_counts_as_multiple_new_observations(study):
    root, repo, basis, config = study
    change_and_queue(study)
    second = drift.enqueue(root, drift.prepare(root, config), record(study, 2))
    assert second["status"] == "no_delta"
    (repo / "code.py").write_text("TIMEOUT = 1\n")
    drift.enqueue(root, drift.prepare(root, config), record(study, 3))
    repeated = change_and_queue(study, 1)
    assert repeated["status"] == "duplicate_event"
    repeated = drift.enqueue(root, drift.prepare(root, config), record(study, 4))
    assert repeated["status"] == "duplicate_evidence"


@pytest.mark.parametrize("where", ["before", "during"])
@pytest.mark.parametrize("mutation", ["config", "contract", "source"])
def test_changed_identity_cannot_be_reported_as_current(study, where, mutation):
    root, repo, basis, config = study
    change_and_queue(study)

    def change():
        path = {"config": config, "contract": basis, "source": record(study)}[mutation]
        value = json.loads(path.read_text())
        if mutation == "config":
            value["mode"] = "off"
        elif mutation == "contract":
            value["acceptance"] = ["A newly approved different outcome"]
        else:
            value["todo_id"] = "changed-task"
        atomic_json(path, value)

    if where == "before":
        change()
    calls = []

    def send(request, *args):
        calls.append(request)
        if where == "during":
            change()
        return {"response": response(request)}

    actual = drift.drain(root, config, transport=send, credential=lambda: "fixture")
    if where == "before" and mutation == "config":
        assert actual["status"] == "disabled" and not calls
    else:
        event = drift.status(root)["events"][0]
        assert event["status"] in {"not_evaluated", "stale"} and not event.get(
            "judgments"
        )
        assert len(calls) == (where == "during")


def test_future_workspace_changes_do_not_invalidate_sealed_historical_evidence(study):
    root, repo, basis, config = study
    change_and_queue(study)
    (repo / "code.py").write_text("The next turn is already working\n")
    calls = []
    drift.drain(root, config, transport=provider(calls), credential=lambda: "fixture")
    assert len(calls) == 1 and "next turn" not in json.dumps(calls)
    assert drift.status(root)["historical_only"] is True


def test_unknown_missing_key_and_timeout_are_not_healthy_or_drift(study):
    root, repo, basis, config = study
    change_and_queue(study)
    drift.drain(root, config, transport=forbidden, credential=lambda: None)
    assert drift.status(root)["events"][0]["reason"] == "missing_key"
    change_and_queue(study, 2)

    def timed_out(*args):
        raise TransportFailure("deadline_exceeded", "may_have_been_sent")

    drift.drain(root, config, transport=timed_out, credential=lambda: "fixture")
    assert drift.status(root)["events"][1]["status"] == "failed"
    assert (
        drift.drain(root, config, transport=forbidden, credential=forbidden)[
            "processed"
        ]
        == []
    )
    change_and_queue(study, 3)

    def unknown(request, *args):
        undecided = {name: 0.5 for name in DRIFT_NOULS}
        return {"response": response(request, ["unknown", "unknown"], nouls=undecided)}

    drift.drain(root, config, transport=unknown, credential=lambda: "fixture")
    event = drift.status(root)["events"][2]
    assert event["status"] == "abstained"
    assert event["drift_signal"] == {"noul": None, "choice": None}


def test_contract_change_resets_baseline_without_inventing_progress(study):
    root, repo, basis, config = study
    value = json.loads(basis.read_text())
    value["acceptance"] = ["New task"]
    atomic_json(basis, value)
    assert change_and_queue(study)["status"] == "baseline_reset"
    assert (
        drift.drain(root, config, transport=forbidden, credential=forbidden)[
            "processed"
        ]
        == []
    )


def test_concurrent_duplicate_enqueue_is_one_event(study):
    root, repo, basis, config = study
    (repo / "code.py").write_text("RENAMED = 1\n")
    prepared = drift.prepare(root, config)
    source = record(study)
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(lambda _: drift.enqueue(root, prepared, source), range(2))
        )
    assert sorted(row["status"] for row in results) == ["duplicate_event", "queued"]


def test_consumer_holds_no_capture_lock_or_authority_during_model_call(study):
    root, repo, basis, config = study
    change_and_queue(study)

    def send(request, *args):
        with ThreadPoolExecutor(1) as pool:
            assert (
                pool.submit(change_and_queue, study, 2).result(timeout=5)["status"]
                == "queued"
            )
        return {"response": response(request)}

    drift.drain(root, config, transport=send, credential=lambda: "fixture")
    assert drift.status(root)["counts"] == {"completed": 1, "queued": 1}


@pytest.mark.parametrize("kind", ["symlink", "binary", "oversized"])
def test_invalid_scope_is_not_sent(study, kind):
    root, repo, basis, config = study
    target = repo / "code.py"
    if kind == "symlink":
        target.unlink()
        target.symlink_to(basis)
    elif kind == "binary":
        target.write_bytes(b"\0binary")
    else:
        target.write_text("x" * 32769)
    with pytest.raises(ValueError):
        drift.prepare(root, config)


def test_index_only_change_is_unknown(study):
    root, repo, basis, config = study
    (repo / "code.py").write_text("TIMEOUT = 2\n")
    git(repo, "add", "code.py")
    (repo / "code.py").write_text("TIMEOUT = 1\n")
    item = drift.enqueue(root, drift.prepare(root, config), record(study))
    assert item["status"] == "index_only_change_unknown"


def test_capture_failure_preserves_original_output_and_resets_baseline(study, capsys):
    root, repo, basis, config = study
    source = record(study)
    original = (
        json.dumps({"appended": True, "dry_run": False, "json_path": str(source)})
        + "\n"
    )

    def invoke(args):
        (repo / "code.py").write_text("changed during owner invocation\n")
        print(original, end="")
        return 0

    assert refresh(["refresh-state"], root, config, invoke) == 0
    captured = capsys.readouterr()
    assert captured.out == original
    assert json.loads(captured.err)["jev_drift"]["status"] == "capture_failed"
    assert drift.state(root)["baseline"] is None
    assert change_and_queue(study, 2)["status"] == "baseline_reset"


def test_queued_then_crash_reuses_provider_result(study, monkeypatch):
    root, repo, basis, config = study
    change_and_queue(study)
    calls = []
    actual = drift.atomic_json

    def crash(path, value):
        if path.parent.name == "results":
            raise OSError("simulated crash after request receipt")
        actual(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(drift, "atomic_json", crash)
        with pytest.raises(OSError):
            drift.drain(
                root, config, transport=provider(calls), credential=lambda: "fixture"
            )
    drift.drain(root, config, transport=forbidden, credential=lambda: "fixture")
    assert len(calls) == 1 and drift.status(root)["counts"] == {"completed": 1}


def test_assist_rejected_and_state_not_overwritten(study):
    root, repo, basis, config = study
    with pytest.raises(ValueError, match="state_exists"):
        drift.initialize(root, repo, basis, config, ["code.py"])
    value = json.loads(config.read_text())
    value["mode"] = "assist"
    atomic_json(config, value)
    with pytest.raises(ValueError, match="off_or_shadow"):
        drift.drain(root, config, transport=forbidden, credential=forbidden)


def test_off_on_revokes_inflight_result_even_with_same_config_bytes(study):
    root, repo, basis, config = study
    change_and_queue(study)

    def send(request, *args):
        drift.configure(root, "off")
        drift.configure(root, "shadow")
        return {"response": response(request)}

    drift.drain(root, config, transport=send, credential=lambda: "fixture")
    assert drift.status(root)["events"][0]["status"] == "stale"
    assert change_and_queue(study, 2)["status"] == "baseline_reset"


def test_deleted_provider_detail_does_not_repeat_ambiguous_request(study, monkeypatch):
    root, repo, basis, config = study
    change_and_queue(study)
    original = drift.atomic_json

    def crash(path, value):
        if path.parent.name == "results":
            raise OSError("crash after dispatch")
        original(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(drift, "atomic_json", crash)
        with pytest.raises(OSError):
            drift.drain(
                root, config, transport=provider([]), credential=lambda: "fixture"
            )
    for path in (root / "requests").glob("*.json"):
        if path.name != "manifest.json":
            path.unlink()
    drift.drain(root, config, transport=forbidden, credential=lambda: "fixture")
    assert drift.status(root)["events"][0]["reason"] == "prior_attempt_unresolved"


def test_same_turn_checkpoint_supplement_is_not_a_second_observation(study):
    root, repo, basis, config = study
    change_and_queue(study)
    path = record(study)
    value = json.loads(path.read_text())
    value["vision_checkpoint"] = {"satisfied": True}
    atomic_json(path, value)
    assert (
        drift.enqueue(root, drift.prepare(root, config), path)["status"]
        == "duplicate_event"
    )


def test_pending_limit_resets_capture_baseline_but_preserves_original_success(
    study, monkeypatch, capsys
):
    root, repo, basis, config = study
    monkeypatch.setattr(drift, "MAX_PENDING", 1)
    change_and_queue(study)
    (repo / "code.py").write_text("TIMEOUT = 5\n")
    source = record(study, 2)

    def invoke(args):
        print(
            json.dumps({"appended": True, "dry_run": False, "json_path": str(source)})
        )
        return 0

    assert refresh(["refresh-state"], root, config, invoke) == 0
    assert (
        json.loads(capsys.readouterr().err)["jev_drift"]["status"] == "capture_failed"
    )
    assert drift.state(root)["baseline"] is None and drift.status(root)["counts"] == {
        "queued": 1
    }


def test_deletion_mode_and_no_final_newline_remain_visible(study):
    root, repo, basis, config = study
    before = stable_capture(repo, ["code.py"])
    (repo / "code.py").write_text("TIMEOUT = 2")
    changed = stable_capture(repo, ["code.py"])
    text = delta(before, changed)
    assert (
        "-TIMEOUT = 1\n+TIMEOUT = 2\n" in text and "final_newline True -> False" in text
    )
    (repo / "code.py").chmod(0o755)
    executable = stable_capture(repo, ["code.py"])
    assert "executable False -> True" in delta(changed, executable)
    (repo / "code.py").unlink()
    assert "present True -> False" in delta(
        executable, stable_capture(repo, ["code.py"])
    )


def test_private_file_permissions_and_secret_like_scope_rejection(study):
    root, repo, basis, config = study
    assert (root / "state.json").stat().st_mode & 0o777 == 0o600
    (repo / "code.py").write_text("apikey_" + "x" * 30)
    with pytest.raises(ValueError, match="credential_like"):
        drift.prepare(root, config)
    assert "apikey_" not in (root / "state.json").read_text()


def test_wrong_goal_record_cannot_be_used(study):
    root, repo, basis, config = study
    source = record(study)
    value = json.loads(source.read_text())
    value["goal_id"] = "some-other-goal"
    atomic_json(source, value)
    with pytest.raises(ValueError, match="run_goal"):
        drift.enqueue(root, drift.prepare(root, config), source)
    assert drift.status(root)["counts"] == {}


def test_evidence_only_work_is_not_dropped_as_no_code_delta(study):
    root, repo, basis, config = study
    evidence = repo / "test-result.txt"
    evidence.write_text("Before: no experiment has run.\n")
    value = json.loads(basis.read_text())
    value["evidence"] = [{"ref": "test-result.txt"}]
    atomic_json(basis, value)
    assert (
        drift.enqueue(root, drift.prepare(root, config), record(study))["status"]
        == "baseline_reset"
    )
    evidence.write_text(
        "After: a negative experiment excluded the retry-count hypothesis.\n"
    )
    assert (
        drift.enqueue(root, drift.prepare(root, config), record(study, 2))["status"]
        == "queued"
    )
    calls = []
    drift.drain(root, config, transport=provider(calls), credential=lambda: "fixture")
    assert "negative experiment excluded" in json.dumps(calls)
    context = next(
        item
        for item in calls[0]["state"]["goal_basis"]["evidence"]
        if item["ref"] == "scoped-checkpoint-context"
    )
    observed = json.loads(context["text"])
    assert observed["before"]["code.py"]["text"] == "TIMEOUT = 1\n"
    assert observed["after"]["code.py"]["text"] == "TIMEOUT = 1\n"


@pytest.mark.parametrize("bad_state", [[], {}, {"schema": drift.SCHEMA}])
def test_corrupt_observer_state_cannot_block_original_refresh(study, bad_state, capsys):
    root, repo, basis, config = study
    source = record(study)
    atomic_json(root / "state.json", bad_state)

    def invoke(args):
        print(
            json.dumps({"appended": True, "dry_run": False, "json_path": str(source)})
        )
        return 0

    assert refresh(["refresh-state"], root, config, invoke) == 0
    out = capsys.readouterr()
    assert json.loads(out.out)["appended"] is True
    assert json.loads(out.err)["jev_drift"]["status"] == "capture_failed"


def test_enable_validation_precedes_configuration_write(study):
    root, repo, basis, config = study
    drift.configure(root, "off")
    value = json.loads(config.read_text())
    value["model"] = ""
    atomic_json(config, value)
    before = config.read_bytes(), (root / "state.json").read_bytes()
    with pytest.raises(ValueError, match="pinned_model"):
        drift.configure(root, "shadow")
    assert before == (config.read_bytes(), (root / "state.json").read_bytes())


def test_full_context_over_request_budget_abstains_without_truncating_or_sending(study):
    root, repo, basis, config = study
    value = json.loads(config.read_text())
    value["limits"] = {"max_request_bytes": 1024}
    atomic_json(config, value)
    (repo / "code.py").write_text("# " + "context " * 150 + "\nTIMEOUT = 2\n")
    drift.enqueue(root, drift.prepare(root, config), record(study))
    drift.drain(root, config, transport=forbidden, credential=forbidden)
    assert drift.status(root)["events"][0]["reason"] == "request_too_large"
