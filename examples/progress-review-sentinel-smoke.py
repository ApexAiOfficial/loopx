#!/usr/bin/env python3
"""Smoke-test the progress-review sentinel differential from recorded answers.

Replays the committed comparison matrix against the committed provider
recordings, so it needs no credential and no network. It asserts the harness
shape and that the replay reproduces the committed summary: the typed repeat
fuse stays quiet on every self-declared `advanced` round, while each receipt
signal's first-flag rounds match what the live run recorded.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(1, str(REPO_ROOT / "packages" / "loopx-jev" / "src"))

from loopx_jev.sentinel_compare import COMPARISON_SCHEMA, compare  # noqa: E402
from loopx_jev.sentinel_matrix import load_sentinel_matrix  # noqa: E402

FIXTURES = REPO_ROOT / "packages" / "loopx-jev" / "tests" / "fixtures" / "sentinel"


def deterministic_view(comparison: dict) -> dict:
    """Project the fields that must reproduce from recordings alone."""

    return {
        case["case_id"]: {
            "first_flag_round": case["first_flag_round"],
            "first_obligation_round": case["first_obligation_round"],
            "typed_repeat_first_round": case["baseline"]["typed_repeat_first_round"],
            "statuses": [row["status"] for row in case["rounds"]],
        }
        for case in comparison["cases"]
    }


def main() -> int:
    matrix = load_sentinel_matrix(FIXTURES / "matrix.json")
    expected_path = FIXTURES / "expected_summary.json"
    if not expected_path.is_file():
        print("expected_summary.json is missing; record it with `loopx-jev sentinel compare --live`")
        return 1
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="loopx-sentinel-smoke-") as temporary:
        comparison = compare(
            matrix,
            responses=FIXTURES / "responses",
            live=False,
            model=expected["model"],
            deadline_ms=5000,
            drift_threshold=2,
        )
        Path(temporary, "comparison.json").write_text(json.dumps(comparison), encoding="utf-8")
    assert comparison["schema_version"] == COMPARISON_SCHEMA
    assert comparison["execution"] == "recorded_replay"
    assert comparison["aggregate"]["cases"] == 16
    assert comparison["aggregate"]["baseline"]["typed_repeat_fired_cases"] == 0
    assert comparison["aggregate"]["signals"] == expected["live_aggregate"]["signals"]
    for case in comparison["cases"]:
        assert all(row["status"] != "not_captured" for row in case["rounds"]), case["case_id"]
        assert all(
            row["execution_kind"] == "recorded_replay"
            for row in case["rounds"]
            if row["status"] in {"completed", "abstained", "failed"}
        ), case["case_id"]
    actual = deterministic_view(comparison)
    if actual != expected["deterministic_view"]:
        for case_id, view in actual.items():
            if view != expected["deterministic_view"].get(case_id):
                print("mismatch", case_id, json.dumps(view), json.dumps(expected["deterministic_view"].get(case_id)))
        return 1
    print(
        json.dumps(
            {
                "status": "ok",
                "cases": comparison["aggregate"]["cases"],
                "signals": comparison["aggregate"]["signals"],
                "baseline": comparison["aggregate"]["baseline"]["typed_repeat_fired_cases"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
