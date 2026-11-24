"""Read-only rendering never upgrades association or unknown checks to acceptance."""
from copy import deepcopy

import pytest

from loopx.presentation.renderers.goal_acceptance_observation_markdown import (
    append_goal_acceptance_observation_markdown,
)


def render(contract=None, *, source="release-demo"):
    observation = {
        "schema_version": "goal_acceptance_observation_projection_v0",
        "goal_id": source, "historical_progress": [], "acceptance_gaps": [], "guards": [],
    }
    if contract is not None:
        observation["goal_acceptance_contract"] = contract
    lines = []
    append_goal_acceptance_observation_markdown(
        lines, {"id": "release-demo", "acceptance_observation": observation}
    )
    return "\n".join(lines)


@pytest.fixture
def contract():
    return {
        "enabled": True, "revision": 7, "digest": "a" * 64, "status": "held",
        "non_goals": [], "held_todo_ids": ["todo_unbound", "todo_stale"], "verification": None,
        "objective": "Deliver a recoverable release",
        "criteria": [{"id": "recovery", "description": "An independent recovery check passes."}],
        "tasks": [
            {"todo_id": "todo_confirmed", "state": "ready", "criterion_ids": ["recovery"]},
            {"todo_id": "todo_unbound", "state": "unbound", "criterion_ids": [], "reason": "No criterion is associated."},
            {"todo_id": "todo_stale", "state": "stale", "criterion_ids": ["recovery"], "reason": "Prior contract revision."},
        ],
    }


def test_absent_and_disabled_preserve_baseline(contract):
    baseline = render()
    for disabled in ({"enabled": False}, {**contract, "enabled": False, "verification": {"status": "passed"}}):
        assert render(disabled) == baseline


@pytest.mark.parametrize("status, expected", [
    (None, "unknown"), ("unverified", "artifact checks not verified"),
    ("failed", "artifact checks failed"), ("stale", "artifact checks stale"),
    ("accepted", "artifact checks passed"), ("held", "task associations require confirmation"),
    ("partial", "task checks passed; Goal-wide verification unknown"),
])
def test_source_revision_and_independent_states(contract, status, expected):
    contract["status"] = status
    if status not in {None, "unverified"}:
        contract["verification"] = {
            "operation_id": "verify-release-7", "contract_revision": 6 if status == "stale" else 7,
            "contract_digest": "c" * 64 if status == "stale" else contract["digest"],
            "todo_id": "todo_confirmed" if status == "partial" else None,
            "results": [{"criterion_id": "recovery", "passed": status != "failed", "exit_code": 1 if status == "failed" else 0}],
        }
    before = deepcopy(contract)
    output = render(contract)
    assert f"artifact verification: {expected}" in output
    assert "todo\\_confirmed: task association confirmed" in output
    assert "todo\\_unbound: task association missing; criteria=unknown" in output
    assert "todo\\_stale: task association stale" in output
    assert "Prior contract revision." in output
    assert "Goal source: release-demo" in output
    assert "contract revision: 7" in output
    assert contract["digest"] in output
    assert "criterion recovery: An independent recovery check passes." in output
    assert "does not automatically approve or complete the Goal" in output
    if status != "accepted":
        assert "artifact checks passed" not in output
    if status == "stale":
        assert "contract revision: 6" in output and "c" * 64 in output
    if status == "partial":
        assert "verification scope: todo\\_confirmed" in output
    assert contract == before


def test_empty_observations_remain_unknown_and_other_goal_is_not_used(contract):
    assert "task associations: unknown" in render({**contract, "tasks": []})
    other_goal = render(contract, source="other-goal")
    assert "source unavailable; acceptance unknown" in other_goal
    assert contract["digest"] not in other_goal
    assert "task association confirmed" not in other_goal


def test_revision_is_read_from_source_and_markup_is_escaped(contract):
    updated = {**contract, "revision": 8, "digest": "sha256:" + "b" * 64, "objective": "[example](https://example.com)\n# title"}
    output = render(updated)
    assert "contract revision: 8" in output and updated["digest"] in output
    assert contract["digest"] not in output
    assert "\n# title" not in output
    assert "\\[example\\]" in output
