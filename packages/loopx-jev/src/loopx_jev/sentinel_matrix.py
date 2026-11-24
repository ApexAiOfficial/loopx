"""Load a frozen comparison matrix: recorded work sequences with gold labels.

A matrix is a JSON document plus fixture files. Every case is a short sequence
of scoped file states with the Agent's self-report per round and one gold label
fixed before any provider call. The loader is strict so a case cannot smuggle
prose, oversized material or an unbounded number of rounds into a run.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from loopx.control_plane.work_items.progress_result import ProgressResultClass

from .config import read_json

MATRIX_SCHEMA = "loopx_jev_sentinel_matrix_v0"
MAX_CASES = 16
MAX_ROUNDS = 6
MAX_PATHS = 8
MAX_FILE_BYTES = 32768
MAX_ROUND_BYTES = 32768
CASE_KINDS = ("constructed", "real_commit")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_RESULT_CLASSES = {item.value for item in ProgressResultClass}


def _token(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise ValueError(f"{field} must be a bounded identifier")
    return value


def _text(value: Any, *, field: str, limit: int = 400) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{field} must be non-empty text within {limit} characters")
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValueError(f"{field} contains control characters")
    return value.strip()


def _relative_path(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or ".git" in path.parts:
        raise ValueError(f"{field} escapes the fixture directory")
    return path.as_posix()


def _read_fixture(base: Path, reference: Any, *, field: str) -> str | None:
    if reference is None:
        return None
    target = base / _relative_path(reference, field=field)
    if target.is_symlink() or not target.is_file():
        raise ValueError(f"{field} references a missing fixture file")
    raw = target.read_bytes()
    if len(raw) > MAX_FILE_BYTES or b"\0" in raw:
        raise ValueError(f"{field} fixture is oversized or binary")
    return raw.decode("utf-8")


def _files(base: Path, value: Any, paths: list[str], *, field: str) -> dict[str, str | None]:
    if not isinstance(value, dict) or set(value) - set(paths):
        raise ValueError(f"{field} must map only declared scoped paths")
    files: dict[str, str | None] = {}
    total = 0
    for path in paths:
        if path not in value:
            continue
        text = _read_fixture(base, value[path], field=f"{field}.{path}")
        files[path] = text
        total += len(text.encode("utf-8")) if text is not None else 0
    if total > MAX_ROUND_BYTES:
        raise ValueError(f"{field} exceeds the per-round byte budget")
    return files


def load_sentinel_matrix(path: Path) -> dict[str, Any]:
    document, digest = read_json(path, 256 * 1024)
    if not isinstance(document, dict) or document.get("schema_version") != MATRIX_SCHEMA:
        raise ValueError(f"matrix must use {MATRIX_SCHEMA}")
    threshold = document.get("label_probability_threshold", 0.6)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0.5 <= threshold <= 1:
        raise ValueError("label_probability_threshold must be within [0.5, 1]")
    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("matrix cases must be a non-empty array")
    if len(raw_cases) > MAX_CASES:
        raise ValueError(f"matrix supports at most {MAX_CASES} cases")
    base = path.resolve().parent
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_cases):
        field = f"cases[{index}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{field} must be an object")
        case_id = _token(raw.get("case_id"), field=f"{field}.case_id")
        if case_id in seen:
            raise ValueError(f"duplicate case id: {case_id}")
        seen.add(case_id)
        kind = raw.get("kind")
        if kind not in CASE_KINDS:
            raise ValueError(f"{field}.kind must be one of {CASE_KINDS}")
        basis = raw.get("basis")
        if not isinstance(basis, dict) or set(basis) - {"objective", "acceptance", "non_goals"}:
            raise ValueError(f"{field}.basis has unexpected fields")
        objective = _text(basis.get("objective"), field=f"{field}.basis.objective")
        acceptance = basis.get("acceptance")
        if not isinstance(acceptance, list) or not acceptance or len(acceptance) > 8:
            raise ValueError(f"{field}.basis.acceptance must list 1-8 criteria")
        acceptance = [_text(item, field=f"{field}.basis.acceptance[]") for item in acceptance]
        non_goals = basis.get("non_goals", [])
        if not isinstance(non_goals, list) or len(non_goals) > 8:
            raise ValueError(f"{field}.basis.non_goals must be a short list")
        non_goals = [_text(item, field=f"{field}.basis.non_goals[]") for item in non_goals]
        paths = raw.get("paths")
        if not isinstance(paths, list) or not 1 <= len(paths) <= MAX_PATHS or len(set(paths)) != len(paths):
            raise ValueError(f"{field}.paths must list 1-{MAX_PATHS} unique scoped files")
        paths = [_relative_path(item, field=f"{field}.paths[]") for item in paths]
        baseline = _files(base, raw.get("baseline", {}), paths, field=f"{field}.baseline")
        raw_rounds = raw.get("rounds")
        if not isinstance(raw_rounds, list) or not 1 <= len(raw_rounds) <= MAX_ROUNDS:
            raise ValueError(f"{field}.rounds must list 1-{MAX_ROUNDS} rounds")
        rounds: list[dict[str, Any]] = []
        for round_index, raw_round in enumerate(raw_rounds, start=1):
            round_field = f"{field}.rounds[{round_index}]"
            if not isinstance(raw_round, dict) or set(raw_round) - {"self_report", "files"}:
                raise ValueError(f"{round_field} has unexpected fields")
            report = raw_round.get("self_report")
            if not isinstance(report, dict) or set(report) - {"result_class", "hypothesis_id", "surface_id", "probe_kind"}:
                raise ValueError(f"{round_field}.self_report has unexpected fields")
            result_class = report.get("result_class", "advanced")
            if result_class not in _RESULT_CLASSES:
                raise ValueError(f"{round_field}.self_report.result_class is not typed")
            normalized_report: dict[str, str] = {"result_class": str(result_class)}
            for key in ("hypothesis_id", "surface_id", "probe_kind"):
                if report.get(key) is not None:
                    normalized_report[key] = _token(report[key], field=f"{round_field}.self_report.{key}")
            rounds.append(
                {
                    "round": round_index,
                    "self_report": normalized_report,
                    "files": _files(base, raw_round.get("files", {}), paths, field=f"{round_field}.files"),
                }
            )
        gold = raw.get("gold")
        if not isinstance(gold, dict) or set(gold) - {"drift_from_round", "labeler", "note"}:
            raise ValueError(f"{field}.gold has unexpected fields")
        drift_from = gold.get("drift_from_round")
        if drift_from is not None and (
            isinstance(drift_from, bool) or not isinstance(drift_from, int) or not 1 <= drift_from <= len(rounds)
        ):
            raise ValueError(f"{field}.gold.drift_from_round must be null or a round number")
        provenance = raw.get("provenance")
        if provenance is not None and (
            not isinstance(provenance, dict) or set(provenance) - {"commit", "repository"}
        ):
            raise ValueError(f"{field}.provenance has unexpected fields")
        cases.append(
            {
                "case_id": case_id,
                "kind": kind,
                "provenance": dict(provenance) if provenance else None,
                "basis": {"objective": objective, "acceptance": acceptance, "non_goals": non_goals},
                "paths": paths,
                "baseline": baseline,
                "rounds": rounds,
                "gold": {
                    "drift_from_round": drift_from,
                    "labeler": _text(gold.get("labeler"), field=f"{field}.gold.labeler", limit=80),
                    "note": _text(gold.get("note", "n/a"), field=f"{field}.gold.note"),
                },
            }
        )
    return {
        "schema_version": MATRIX_SCHEMA,
        "matrix_digest": digest,
        "label_probability_threshold": float(threshold),
        "cases": cases,
    }


__all__ = ["MATRIX_SCHEMA", "load_sentinel_matrix"]
