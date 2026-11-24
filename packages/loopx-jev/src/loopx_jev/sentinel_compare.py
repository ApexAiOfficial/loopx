"""Replay or record the comparison matrix: typed fuse versus external review.

For every case the harness builds a real Git repository, drives the real
observer (`initialize` → `enqueue` → `drain`) round by round, and records what
the LoopX typed repeat fuse, the periodic review, and each receipt signal would
have flagged at each round. Provider answers are recorded on `--live` and
replayed otherwise, so the receipt reproduces without a credential.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import time
from typing import Any, Callable

from loopx.control_plane.work_items.autonomous_replan_ack import (
    AUTONOMOUS_REPLAN_ACK_MATERIAL_RUN_WINDOW,
    autonomous_replan_ack_recorded,
)
from loopx.control_plane.work_items.external_progress_review import (
    external_progress_review_trigger,
)
from loopx.control_plane.work_items.progress_observation import (
    PROGRESS_REPEAT_THRESHOLD,
    normalize_progress_observation,
    typed_progress_repeat_trigger,
)

from . import drift
from .config import Config, strict_json
from .protocol import request_bytes
from .store import atomic_json
from .transport import TransportFailure, send

COMPARISON_SCHEMA = "loopx_jev_sentinel_comparison_v0"
AGENT_ID = "sentinel-agent"
SIGNALS = ("noul", "choice")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def _write_files(repo: Path, files: dict[str, str | None]) -> None:
    for name, text in files.items():
        target = repo / name
        if text is None:
            if target.exists():
                target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def recording_key(request: dict[str, Any]) -> str:
    """Stable key for one provider request, independent of temp config paths."""

    return hashlib.sha256(request_bytes(request)).hexdigest()


def recording_transport(
    responses: Path, *, live: bool
) -> Callable[[dict[str, Any], Config, str], dict[str, Any]]:
    responses.mkdir(parents=True, exist_ok=True)

    def transport(request: dict[str, Any], config: Config, key: str) -> dict[str, Any]:
        path = responses / f"{recording_key(request)}.json"
        if not live:
            if not path.is_file():
                raise TransportFailure("no_recorded_response", "not_sent")
            recorded = strict_json(path.read_bytes())
            if not isinstance(recorded, dict) or "response" not in recorded:
                raise TransportFailure("invalid_recorded_response", "not_sent")
            return {"response": recorded["response"], "replayed_recording": True}
        envelope = send(request, config, key)
        response = envelope.get("response")
        if isinstance(response, dict):
            sanitized = {
                "model": response.get("model"),
                "answers": response.get("answers"),
                "usage": response.get("usage"),
            }
            atomic_json(
                path,
                {
                    "schema": "loopx_jev_recorded_response_v0",
                    "request_key": recording_key(request),
                    "recorded_at": time.time(),
                    "response": sanitized,
                    "worker_timing_ns": envelope.get("worker_timing_ns"),
                },
            )
        return envelope

    # The runner labels non-`send` transports as injected fixtures; name the
    # recording wrapper so live recordings and replays stay distinguishable.
    transport.execution_kind = "live_provider_recording" if live else "recorded_replay"  # type: ignore[attr-defined]
    return transport


def _goal_id(case_id: str) -> str:
    """Stable, label-free identity: the case name never reaches the run or the model."""

    return "sentinel-" + hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:16]


def _run_record(case_id: str, round_number: int) -> dict[str, Any]:
    return {
        "goal_id": _goal_id(case_id),
        "classification": "bounded_delivery",
        "generated_at": f"2026-09-21T00:{round_number // 60:02d}:{round_number % 60:02d}Z",
        "turn_instance_id": f"{case_id}-r{round_number}",
        "agent_id": AGENT_ID,
    }


def _baseline_runs(case: dict[str, Any], upto: int) -> list[dict[str, Any]]:
    """Newest-first typed run rows the core fuse would see after round `upto`."""

    rows: list[dict[str, Any]] = []
    for round_item in case["rounds"][:upto]:
        record = _run_record(case["case_id"], round_item["round"])
        observation = {"schema_version": "typed_progress_observation_v0", **round_item["self_report"]}
        record["progress_observation"] = normalize_progress_observation(observation)
        rows.append(record)
    return rows[::-1]


def _receipt_like(case: dict[str, Any], round_item: dict[str, Any], event: dict[str, Any], sequence: int) -> dict[str, Any]:
    return {
        "receipt_id": event["event_id"],
        "event_id": event["event_id"],
        "evidence_id": event.get("evidence_id") or "",
        "contract_revision": "matrix",
        "sequence": sequence,
        "status": event.get("status"),
        "reason": event.get("reason"),
        "run": {
            "turn_instance_id": f"{case['case_id']}-r{round_item['round']}",
            "generated_at": _run_record(case["case_id"], round_item["round"])["generated_at"],
            "agent_id": AGENT_ID,
        },
        "judgments": {"choice": event.get("judgments"), "noul": event.get("noul")},
        "drift_signal": event.get("drift_signal") or {"noul": None, "choice": None},
    }


def _ns_to_ms(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return round(value / 1_000_000, 3)


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def run_case(
    case: dict[str, Any],
    *,
    workdir: Path,
    model: str,
    threshold: float,
    deadline_ms: int,
    drift_threshold: int,
    transport: Callable[..., dict[str, Any]],
    credential: Callable[[], str | None],
) -> dict[str, Any]:
    repo = workdir / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "sentinel@example.invalid")
    _git(repo, "config", "user.name", "Sentinel Matrix")
    _write_files(repo, case["baseline"])
    if any(text is not None for text in case["baseline"].values()):
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "baseline", "--allow-empty")
    else:
        _git(repo, "commit", "-qm", "baseline", "--allow-empty")
    basis_path = workdir / "basis.json"
    atomic_json(
        basis_path,
        {
            "goal_id": _goal_id(case["case_id"]),
            "objective": case["basis"]["objective"],
            "acceptance": case["basis"]["acceptance"],
            "non_goals": case["basis"]["non_goals"],
            "evidence": [],
        },
    )
    config_path = workdir / "config.json"
    atomic_json(
        config_path,
        {
            "schema_version": "loopx_jev_drift_config_v0",
            "mode": "shadow",
            "scenarios": ["progress_review"],
            "model": model,
            "allow_egress": True,
            # The size-probe case sends an 18 KB module twice (before/after)
            # plus its delta; the observer's allowed ceiling is 128 KB.
            "limits": {
                "deadline_ms": deadline_ms,
                "max_requests_per_run": 20,
                "max_request_bytes": 131072,
            },
            "minimum_label_probability": threshold,
        },
    )
    root = workdir / "observer"
    drift.initialize(root, repo, basis_path, config_path, case["paths"])
    rounds_out: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    first_flag: dict[str, int | None] = {signal: None for signal in SIGNALS}
    first_obligation: dict[str, int | None] = {signal: None for signal in SIGNALS}
    typed_first: int | None = None
    for round_item in case["rounds"]:
        _write_files(repo, round_item["files"])
        record_path = workdir / f"run-{round_item['round']}.json"
        atomic_json(record_path, _run_record(case["case_id"], round_item["round"]))
        queued = drift.enqueue(root, drift.prepare(root, config_path), record_path)
        evaluated: dict[str, Any] | None = None
        if queued["status"] == "queued":
            drift.drain(root, config_path, transport=transport, credential=credential)
            events = {row["event_id"]: row for row in drift.status(root)["events"]}
            evaluated = events.get(queued["event_id"])
        # The typed fuse only ever sees the Agent's own typed self-report.
        baseline_rows = _baseline_runs(case, round_item["round"])
        typed = typed_progress_repeat_trigger(
            baseline_rows, agent_id=AGENT_ID, threshold=PROGRESS_REPEAT_THRESHOLD
        )
        if typed and typed_first is None:
            typed_first = round_item["round"]
        row: dict[str, Any] = {
            "round": round_item["round"],
            "self_report": round_item["self_report"],
            "capture_status": queued["status"],
            "status": evaluated.get("status") if evaluated else "not_captured",
            "drift_signal": (evaluated or {}).get("drift_signal") or {"noul": None, "choice": None},
            "judgments": (evaluated or {}).get("judgments"),
            "noul": (evaluated or {}).get("noul"),
            "reason": (evaluated or {}).get("reason"),
            "execution_kind": ((evaluated or {}).get("execution_kind")),
            "typed_repeat_fires": bool(typed),
        }
        timing = (evaluated or {}).get("assessment_timing_ns") or {}
        row["latency_ms"] = {
            "assessment_total": _ns_to_ms((evaluated or {}).get("assessment_total_ns")),
            "transport_inclusive": _ns_to_ms(timing.get("transport_inclusive")),
            "request_to_headers": _ns_to_ms(((evaluated or {}).get("worker_timing_ns") or {}).get("request_to_headers")),
        }
        usage = (evaluated or {}).get("usage") or {}
        row["input_tokens"] = usage.get("input_tokens")
        if evaluated is not None:
            receipts.append(_receipt_like(case, round_item, evaluated, len(receipts)))
        for signal in SIGNALS:
            if row["drift_signal"].get(signal) is True and first_flag[signal] is None:
                first_flag[signal] = round_item["round"]
            if first_obligation[signal] is None:
                # Receipt rows and run rows share turn identity; the core rule is
                # evaluated exactly as `assist` would evaluate it after this round.
                trigger = external_progress_review_trigger(
                    baseline_rows,
                    receipts=receipts,
                    agent_id=AGENT_ID,
                    threshold=drift_threshold,
                    signal=signal,
                    contract_revision="matrix",
                    ack_recorded=autonomous_replan_ack_recorded,
                )
                if trigger:
                    first_obligation[signal] = round_item["round"]
        rounds_out.append(row)
    gold_round = case["gold"]["drift_from_round"]
    false_flags = {
        signal: [
            row["round"]
            for row in rounds_out
            if row["drift_signal"].get(signal) is True
            and (gold_round is None or row["round"] < gold_round)
        ]
        for signal in SIGNALS
    }
    return {
        "case_id": case["case_id"],
        "kind": case["kind"],
        "provenance": case["provenance"],
        "gold": case["gold"],
        "rounds": rounds_out,
        "baseline": {
            "typed_repeat_first_round": typed_first,
            "periodic_review_round": AUTONOMOUS_REPLAN_ACK_MATERIAL_RUN_WINDOW,
        },
        "first_flag_round": first_flag,
        "first_obligation_round": first_obligation,
        "false_flag_rounds": false_flags,
        "detected": {
            signal: gold_round is not None
            and first_flag[signal] is not None
            and first_flag[signal] >= gold_round
            for signal in SIGNALS
        },
    }


def _aggregate(cases: list[dict[str, Any]], *, drift_threshold: int) -> dict[str, Any]:
    drift_cases = [case for case in cases if case["gold"]["drift_from_round"] is not None]
    on_goal_cases = [case for case in cases if case["gold"]["drift_from_round"] is None]
    latencies = [
        row["latency_ms"]["assessment_total"]
        for case in cases
        for row in case["rounds"]
        if row["latency_ms"]["assessment_total"] is not None and row["status"] in {"completed", "abstained"}
    ]
    tokens = [
        row["input_tokens"] for case in cases for row in case["rounds"] if isinstance(row["input_tokens"], int)
    ]
    statuses: dict[str, int] = {}
    kinds: dict[str, int] = {}
    for case in cases:
        for row in case["rounds"]:
            statuses[str(row["status"])] = statuses.get(str(row["status"]), 0) + 1
            kind = str(row["execution_kind"] or "none")
            kinds[kind] = kinds.get(kind, 0) + 1
    per_signal: dict[str, Any] = {}
    for signal in SIGNALS:
        detected = [case for case in drift_cases if case["detected"][signal]]
        evaluated_on_goal = [
            case
            for case in on_goal_cases
            if all(
                row["status"] == "completed"
                and isinstance(row["drift_signal"].get(signal), bool)
                for row in case["rounds"]
            )
        ]
        incomplete_on_goal = [
            case
            for case in on_goal_cases
            if any(
                row["status"] != "completed"
                or not isinstance(row["drift_signal"].get(signal), bool)
                for row in case["rounds"]
            )
        ]
        delays = [
            case["first_flag_round"][signal] - case["gold"]["drift_from_round"] for case in detected
        ]
        obligations = [case for case in drift_cases if case["first_obligation_round"][signal] is not None]
        per_signal[signal] = {
            "drift_cases_flagged": f"{len(detected)}/{len(drift_cases)}",
            "drift_cases_reaching_obligation": f"{len(obligations)}/{len(drift_cases)}",
            "median_rounds_after_drift_start_to_first_flag": _median([float(d) for d in delays]),
            "on_goal_cases_with_false_flag": (
                f"{sum(1 for case in evaluated_on_goal if case['false_flag_rounds'][signal])}/{len(evaluated_on_goal)}"
            ),
            "on_goal_cases_without_full_verdict": len(incomplete_on_goal),
            "on_goal_cases_without_full_verdict_with_flag": sum(
                1 for case in incomplete_on_goal if case["false_flag_rounds"][signal]
            ),
            "premature_flags_in_mixed_cases": sum(
                len(case["false_flag_rounds"][signal]) for case in drift_cases
            ),
        }
    return {
        "cases": len(cases),
        "drift_cases": len(drift_cases),
        "on_goal_cases": len(on_goal_cases),
        "baseline": {
            "typed_repeat_fired_cases": sum(
                1 for case in cases if case["baseline"]["typed_repeat_first_round"] is not None
            ),
            "periodic_review_round": AUTONOMOUS_REPLAN_ACK_MATERIAL_RUN_WINDOW,
            "note": (
                "the typed fuse needs identical fingerprints plus a self-declared "
                "unchanged/blocked result; every self-declared advanced round is invisible to it"
            ),
        },
        "signals": per_signal,
        "drift_threshold": drift_threshold,
        "round_status_counts": statuses,
        "execution_kinds": kinds,
        "median_assessment_ms": _median(latencies),
        "p95_assessment_ms": (
            round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 3) if latencies else None
        ),
        "median_input_tokens": _median([float(t) for t in tokens]),
    }


def compare(
    matrix: dict[str, Any],
    *,
    responses: Path,
    live: bool,
    model: str,
    deadline_ms: int,
    drift_threshold: int,
    credential: Callable[[], str | None] | None = None,
) -> dict[str, Any]:
    transport = recording_transport(responses, live=live)
    if credential is None:
        credential = (lambda: os.environ.get("TYPESAFE_API_KEY")) if live else (lambda: "replay")
    cases: list[dict[str, Any]] = []
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="loopx-jev-sentinel-") as temporary:
        for case in matrix["cases"]:
            workdir = Path(temporary) / case["case_id"]
            workdir.mkdir()
            cases.append(
                run_case(
                    case,
                    workdir=workdir,
                    model=model,
                    threshold=matrix["label_probability_threshold"],
                    deadline_ms=deadline_ms,
                    drift_threshold=drift_threshold,
                    transport=transport,
                    credential=credential,
                )
            )
    return {
        "schema_version": COMPARISON_SCHEMA,
        "matrix_digest": matrix["matrix_digest"],
        "model": model,
        "label_probability_threshold": matrix["label_probability_threshold"],
        "execution": "live_provider_recording" if live else "recorded_replay",
        "started_at": started,
        "elapsed_seconds": round(time.time() - started, 3),
        "authority": "none",
        "aggregate": _aggregate(cases, drift_threshold=drift_threshold),
        "cases": cases,
    }


def write_comparison(path: Path, comparison: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(comparison, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


__all__ = ["COMPARISON_SCHEMA", "compare", "recording_key", "recording_transport", "run_case", "write_comparison"]
