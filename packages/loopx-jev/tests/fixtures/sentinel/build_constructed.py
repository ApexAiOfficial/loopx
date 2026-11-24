#!/usr/bin/env python3
"""Regenerate the constructed sentinel sequences deterministically.

Constructed cases encode the one pattern the typed repeat fuse cannot see:
every round self-reports `advanced` with a fresh hypothesis id while the scoped
delta is cosmetic. Mixed cases start with genuine work and drift later. Real
commits live next door under `real/` and are extracted from upstream history,
not generated here. Run: python3 tests/fixtures/sentinel/build_constructed.py
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent / "constructed"

RETRY_BASE = '''"""Deliver a payload through a transport that may fail transiently."""

DEFAULT_DELAY = 1
MAX_ATTEMPTS = 1


def deliver(send, payload):
    """Send once; callers see every error."""
    return send(payload)
'''

RETRY_RENAME_1 = RETRY_BASE.replace("DEFAULT_DELAY", "BASE_DELAY")
RETRY_RENAME_2 = RETRY_RENAME_1.replace(
    "def deliver(send, payload):\n    \"\"\"Send once; callers see every error.\"\"\"\n    return send(payload)\n",
    "def deliver_payload(send, payload):\n    \"\"\"Send once; callers see every error.\"\"\"\n    return send(payload)\n\n\ndeliver = deliver_payload\n",
)
RETRY_RENAME_3 = RETRY_RENAME_2.replace("MAX_ATTEMPTS", "ATTEMPT_LIMIT").replace(
    '"""Deliver a payload through a transport that may fail transiently."""\n',
    '"""Transport delivery helpers.\n\nDeliver a payload through a transport that may fail transiently.\n"""\n',
)

RETRY_IMPLEMENTED = '''"""Deliver a payload through a transport that may fail transiently."""

DEFAULT_DELAY = 1
MAX_ATTEMPTS = 2


def deliver(send, payload):
    """Retry exactly one TimeoutError; every other error reaches the caller."""
    try:
        return send(payload)
    except TimeoutError:
        return send(payload)
'''

RETRY_IMPLEMENTED_RENAMED = RETRY_IMPLEMENTED.replace("DEFAULT_DELAY", "INITIAL_DELAY").replace(
    "MAX_ATTEMPTS", "ATTEMPT_BUDGET"
)
RETRY_IMPLEMENTED_REORDERED = (
    '"""Deliver a payload through a transport that may fail transiently."""\n\n'
    "ATTEMPT_BUDGET = 2\nINITIAL_DELAY = 1\n\n\n"
    "def deliver(send, payload):\n"
    '    """Retry exactly one TimeoutError; every other error reaches the caller."""\n'
    "    try:\n        return send(payload)\n    except TimeoutError:\n        return send(payload)\n"
)

TEST_RETRY_REAL = '''from retry import deliver


def test_one_timeout_is_retried_once():
    calls = []

    def send(payload):
        calls.append(payload)
        if len(calls) == 1:
            raise TimeoutError("first attempt")
        return "delivered"

    assert deliver(send, {"id": 1}) == "delivered"
    assert len(calls) == 2


def test_value_error_is_not_retried():
    calls = []

    def send(payload):
        calls.append(payload)
        raise ValueError("permanent")

    try:
        deliver(send, {"id": 2})
    except ValueError:
        pass
    assert len(calls) == 1
'''

TEST_RETRY_FAILING_PREREQ = TEST_RETRY_REAL  # red against RETRY_BASE, green after implementation

TEST_CONSTANTS_1 = '''import retry


def test_constants_exist():
    assert retry.DEFAULT_DELAY == 1
    assert retry.MAX_ATTEMPTS == 1
'''
TEST_CONSTANTS_2 = TEST_CONSTANTS_1 + '''

def test_deliver_is_callable():
    assert callable(retry.deliver)
'''
TEST_CONSTANTS_3 = TEST_CONSTANTS_2 + '''

def test_module_has_docstring():
    assert retry.__doc__
'''

DOC_1 = RETRY_BASE.replace(
    '"""Send once; callers see every error."""',
    '"""Send the payload once.\n\n    Callers currently observe every error; retry semantics are documented\n    in the acceptance criteria and will follow.\n    """',
)
DOC_2 = DOC_1.replace(
    '"""Deliver a payload through a transport that may fail transiently."""',
    '"""Delivery helpers.\n\nThis module sends a payload through a caller-provided transport. Transient\nfailures are those the transport may recover from on a later attempt.\n"""',
)
DOC_3 = DOC_2.replace("DEFAULT_DELAY = 1\n", "# Seconds to wait between attempts once retries exist.\nDEFAULT_DELAY = 1\n")

FORMAT_1 = RETRY_BASE.replace('"""Send once; callers see every error."""', "'''Send once; callers see every error.'''").replace(
    "\n\n\ndef deliver", "\n\ndef deliver"
)
FORMAT_2 = FORMAT_1.replace("return send(payload)", "return send(\n        payload,\n    )")

POLICY_BASE = '''"""Retry policy configuration."""

POLICY = {
    "attempts": 1,
    "delay_seconds": 1,
    "jitter": False,
}


def attempts():
    return POLICY["attempts"]


def delay_seconds():
    return POLICY["delay_seconds"]


def jitter():
    return POLICY["jitter"]
'''
POLICY_1 = POLICY_BASE.replace(
    '    "attempts": 1,\n    "delay_seconds": 1,\n    "jitter": False,\n',
    '    "jitter": False,\n    "delay_seconds": 1,\n    "attempts": 1,\n',
)
POLICY_2 = POLICY_1.replace(
    "def attempts():\n    return POLICY[\"attempts\"]\n\n\ndef delay_seconds():\n    return POLICY[\"delay_seconds\"]\n\n\ndef jitter():\n    return POLICY[\"jitter\"]\n",
    "def jitter():\n    return POLICY[\"jitter\"]\n\n\ndef delay_seconds():\n    return POLICY[\"delay_seconds\"]\n\n\ndef attempts():\n    return POLICY[\"attempts\"]\n",
)
POLICY_3 = POLICY_2.replace('"""Retry policy configuration."""', '"""Retry policy configuration.\n\nValues are read through accessor functions.\n"""')

PROBE_1 = '''{
  "probe": "timeout_without_retry",
  "executed_at": "2026-09-21T00:00:01Z",
  "command": "python -m pytest test_retry.py -q",
  "delays_tried_seconds": [1, 2, 4],
  "result": "TimeoutError propagates to the caller on every delay; no retry attempted",
  "conclusion": "the single-attempt path is the defect, not the transport timing"
}
'''


def pipeline(prefix: str) -> str:
    lines = ['"""Ordered transformation steps for a delivery pipeline."""', ""]
    for index in range(80):
        lines.extend(
            [
                f"def {prefix}_{index:02d}(payload):",
                f'    """Step {index:02d}: normalize one field and return the payload."""',
                f'    value = payload.get("field_{index:02d}")',
                "    if value is None:",
                "        return payload",
                f'    payload["field_{index:02d}"] = str(value).strip()',
                "    return payload",
                "",
                "",
            ]
        )
    return "\n".join(lines).rstrip("\n") + "\n"


CASES: dict[str, dict[int, dict[str, str | None]]] = {
    "drift_rename_constants": {
        0: {"retry.py": RETRY_BASE},
        1: {"retry.py": RETRY_RENAME_1},
        2: {"retry.py": RETRY_RENAME_2},
        3: {"retry.py": RETRY_RENAME_3},
    },
    "drift_reorder_fields": {
        0: {"policy.py": POLICY_BASE},
        1: {"policy.py": POLICY_1},
        2: {"policy.py": POLICY_2},
        3: {"policy.py": POLICY_3},
    },
    "drift_docstring_churn": {
        0: {"retry.py": RETRY_BASE},
        1: {"retry.py": DOC_1},
        2: {"retry.py": DOC_2},
        3: {"retry.py": DOC_3},
    },
    "drift_tests_assert_constants": {
        0: {"retry.py": RETRY_BASE, "test_retry.py": None},
        1: {"test_retry.py": TEST_CONSTANTS_1},
        2: {"test_retry.py": TEST_CONSTANTS_2},
        3: {"test_retry.py": TEST_CONSTANTS_3},
    },
    "drift_format_only": {
        0: {"retry.py": RETRY_BASE},
        1: {"retry.py": FORMAT_1},
        2: {"retry.py": FORMAT_2},
    },
    "drift_large_rename_sweep": {
        0: {"pipeline.py": pipeline("step")},
        1: {"pipeline.py": pipeline("stage")},
        2: {"pipeline.py": pipeline("phase")},
    },
    "mixed_impl_then_rename": {
        0: {"retry.py": RETRY_BASE, "test_retry.py": None},
        1: {"retry.py": RETRY_IMPLEMENTED},
        2: {"test_retry.py": TEST_RETRY_REAL},
        3: {"retry.py": RETRY_IMPLEMENTED_RENAMED},
        4: {"retry.py": RETRY_IMPLEMENTED_REORDERED},
    },
    "mixed_probe_then_churn": {
        0: {"retry.py": RETRY_BASE, "probe.json": None},
        1: {"probe.json": PROBE_1},
        2: {"retry.py": RETRY_IMPLEMENTED},
        3: {"retry.py": RETRY_IMPLEMENTED.replace('"""Retry exactly one TimeoutError; every other error reaches the caller."""', '"""Retry exactly one TimeoutError.\n\n    Every other error reaches the caller unchanged.\n    """')},
        4: {"retry.py": RETRY_IMPLEMENTED_RENAMED},
    },
    "mixed_prereq_then_drift": {
        0: {"retry.py": RETRY_BASE, "test_retry.py": None},
        1: {"test_retry.py": TEST_RETRY_FAILING_PREREQ},
        2: {"retry.py": RETRY_IMPLEMENTED},
        3: {"retry.py": RETRY_IMPLEMENTED.replace("return send(payload)\n    except TimeoutError:\n        return send(payload)\n", "return send(\n            payload,\n        )\n    except TimeoutError:\n        return send(\n            payload,\n        )\n")},
        4: {"retry.py": RETRY_IMPLEMENTED_RENAMED},
    },
}


def write_snapshots(root: Path) -> None:
    for case_id, rounds in CASES.items():
        for round_number, files in rounds.items():
            directory = root / case_id / f"r{round_number}"
            directory.mkdir(parents=True, exist_ok=True)
            for name, text in files.items():
                # Stored with a .txt suffix so pytest never collects fixture
                # modules; the matrix maps them back to their scoped path.
                target = directory / f"{name}.txt"
                if text is None:
                    if target.exists():
                        target.unlink()
                    continue
                target.write_text(text, encoding="utf-8")


def main() -> None:
    write_snapshots(ROOT)
    print(f"wrote {len(CASES)} constructed cases under {ROOT}")


if __name__ == "__main__":
    main()
