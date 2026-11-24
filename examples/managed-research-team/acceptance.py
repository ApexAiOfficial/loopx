"""Domain validation reads canonical facts; only the TS owner can complete work.

Copied and pinned in the disposable project before any model is launched.
"""
from __future__ import annotations

from pathlib import Path
import sys

from loopx.todos import list_goal_todos
from loopx.control_plane.goals.acceptance import inspect_goal_acceptance
from scenario import assignments, upstream, validate_report, validate_worker

GOAL = "synthetic-managed-research"


def todo_id(actor: str, revision: str) -> str:
    return "todo_" + actor + "-" + revision


def canonical_tasks(root: Path) -> dict[str, dict]:
    result = list_goal_todos(registry_path=root / "registry.json", goal_id=GOAL,
                            runtime_root_arg=str(root / "runtime"))
    acceptance = inspect_goal_acceptance(registry_path=root / "registry.json", goal_id=GOAL,
                                        runtime_root=str(root / "runtime"))
    if result.get("authority_read", {}).get("provider_revision") != acceptance.get("provider_revision"):
        raise ValueError("canonical_dependency_snapshot_changed:retry_readback")
    guards = {row["todo_id"]: row for row in acceptance["goal_acceptance_contract"].get("tasks", [])}
    return {row["todo_id"]: {**row, "goal_acceptance_guard": guards.get(row["todo_id"], {})}
            for row in result["todos"]}


def require_completed(rows: dict[str, dict], actor: str, revision: str) -> dict:
    row = rows.get(todo_id(actor, revision), {})
    if row.get("status") != "done" or row.get("done") is not True:
        raise ValueError("canonical_dependency_incomplete:" + todo_id(actor, revision))
    if row.get("goal_acceptance_guard", {}).get("state") != "ready":
        raise ValueError("canonical_dependency_acceptance_not_ready:" + todo_id(actor, revision))
    return row


def validate_delivery(root: Path) -> dict:
    rows = canonical_tasks(root)
    for assignment in assignments(root):
        require_completed(rows, assignment["worker"], assignment["revision"])
    return validate_report(root)


def validate_member(root: Path, actor: str, revision: str) -> dict:
    dependency = upstream(root, actor, revision)
    if dependency:
        previous_actor, previous_revision = dependency.split("/")
        require_completed(canonical_tasks(root), previous_actor, previous_revision)
        validate_worker(root / previous_actor / previous_revision, previous_revision)
    return validate_worker(root / actor / revision, revision)


if __name__ == "__main__":
    root = Path(sys.argv[1])
    if sys.argv[2] == "report":
        validate_delivery(root)
    else:
        validate_member(root, sys.argv[2], sys.argv[3])
    print("Independent artifact and dependency checks passed")
