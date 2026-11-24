"""The Appendix E retrodiction is a committed check, not a report.

The RFC's own incident list recorded that a mutation corpus which is only
exercised locally is not a test. These tests hold the retrodiction harness to
the same standard: the ledger is well formed, and the count of lessons today's
guard rejects cannot fall below the frozen baseline.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "semantic_incident_retrodiction.py"
LEDGER_PATH = REPO_ROOT / "loopx" / "semantics" / "incident_v0.json"


def load_ledger() -> dict:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def test_ledger_is_well_formed() -> None:
    ledger = load_ledger()
    incidents = ledger["incidents"]
    controls = ledger["negative_controls"]

    assert len(incidents) >= 15, "every Appendix E lesson needs a probe"
    assert len({incident["id"] for incident in incidents}) == len(incidents), "incident ids repeat"
    assert len({control["id"] for control in controls}) == len(controls), "control ids repeat"
    for incident in incidents:
        assert incident["expectation"] in {"caught", "uncovered"}, incident["id"]
        assert incident["defect"].strip() and incident["expected_rule"].strip(), incident["id"]
    assert ledger["caught_baseline"]["total"] == len(incidents)
    assert ledger["caught_baseline"]["negative_control_false_positives"] == 0


def test_retrodiction_holds_its_frozen_baseline() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr

    caught = re.search(r"would_have_caught=(\d+)/(\d+)", result.stdout)
    controls = re.search(r"negative_control_false_positives=(\d+)/", result.stdout)
    assert caught and controls, result.stdout

    ledger = load_ledger()
    baseline = ledger["caught_baseline"]
    assert (int(caught.group(1)), int(caught.group(2))) == (baseline["would_have_caught"], baseline["total"]), (
        "the ledger baseline and the measurement disagree; a lesson that was caught must stay caught"
    )
    assert int(controls.group(1)) <= baseline["negative_control_false_positives"], result.stdout
    assert "appendix_e_lessons=15" in result.stdout, "the ledger no longer covers the RFC's lessons"
