"""Refs GH-C07: per-goal history index writers share one lock.

`write_reserved_run_artifacts` appends to `<runs>/index.jsonl` while
`repair_index_duplicates` rewrites that same file from a snapshot. If only one
side locks, an append that lands after the repair reads the index is still lost,
so the durable invariant is that **both** sides take the lock for the **same**
path. These cases pin that, plus the rule that a dry-run repair stays read-only
and does not block writers.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

from loopx import history
from loopx.control_plane.runtime import run_index_rebuild

GOAL_ID = "goal-history-lock"


@pytest.fixture
def record_lock_calls(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Capture every lock path taken through the history module."""
    taken: list[Path] = []
    real_lock = history.exclusive_run_index_lock

    @contextmanager
    def recording_lock(path: Path, **_kwargs: Any) -> Iterator[Path]:
        taken.append(path)
        with real_lock(path, **_kwargs) as locked:
            yield locked

    monkeypatch.setattr(history, "exclusive_run_index_lock", recording_lock)
    return taken


def _write_artifacts(runs_dir: Path) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    generated_at = "2026-09-16T00:00:00+00:00"
    history.write_reserved_run_artifacts(
        runs_dir=runs_dir,
        generated_at=generated_at,
        record={"goal_id": GOAL_ID, "generated_at": generated_at},
        index_record={"goal_id": GOAL_ID, "generated_at": generated_at},
        payload={"goal_id": GOAL_ID, "generated_at": generated_at},
        render_markdown=lambda payload: "# record\n",
    )
    return runs_dir / "index.jsonl"


def test_append_takes_the_goal_index_lock(tmp_path: Path, record_lock_calls: list[Path]) -> None:
    index_path = _write_artifacts(tmp_path / "runs")

    assert record_lock_calls == [index_path], record_lock_calls
    assert index_path.exists()


def test_append_is_visible_after_the_lock_released(
    tmp_path: Path, record_lock_calls: list[Path]
) -> None:
    index_path = _write_artifacts(tmp_path / "runs")

    rows = [
        json.loads(line)
        for line in index_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["goal_id"] for row in rows] == [GOAL_ID]


def _history_fixture(root: Path) -> tuple[Path, Path]:
    runtime_root = root / "runtime"
    index_path = runtime_root / "goals" / GOAL_ID / "runs" / "index.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    row = {"goal_id": GOAL_ID, "generated_at": "2026-09-16T00:00:00+00:00", "kind": "run"}
    index_path.write_text(
        "".join(json.dumps(row) + "\n" for _ in range(2)), encoding="utf-8"
    )
    registry_path = root / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "common_runtime_root": str(runtime_root),
                "projects": [],
                "goals": [],
            }
        ),
        encoding="utf-8",
    )
    return registry_path, runtime_root


def test_repair_locks_the_same_index_path_on_execute(
    tmp_path: Path, record_lock_calls: list[Path]
) -> None:
    registry_path, runtime_root = _history_fixture(tmp_path)
    index_path = runtime_root / "goals" / GOAL_ID / "runs" / "index.jsonl"

    history.repair_index_duplicates(
        registry_path=registry_path,
        runtime_root_override=str(runtime_root),
        goal_id=GOAL_ID,
        limit=10,
        execute=True,
    )

    assert record_lock_calls == [index_path], record_lock_calls


def test_repair_dry_run_does_not_take_the_write_lock(
    tmp_path: Path, record_lock_calls: list[Path]
) -> None:
    registry_path, runtime_root = _history_fixture(tmp_path)

    result = history.repair_index_duplicates(
        registry_path=registry_path,
        runtime_root_override=str(runtime_root),
        goal_id=GOAL_ID,
        limit=10,
        execute=False,
    )

    assert result["dry_run"] is True
    assert record_lock_calls == [], "a read-only repair must not block writers"


def test_collision_rebuild_preserves_append_started_after_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    index_path = runs_dir / "index.jsonl"
    generated_at = "2026-09-16T00:00:00+00:00"
    shared_paths = {
        "json_path": str(runs_dir / "legacy.json"),
        "markdown_path": str(runs_dir / "legacy.md"),
    }
    collision_rows = [
        {
            "goal_id": GOAL_ID,
            "generated_at": generated_at,
            "classification": "quota_monitor_poll",
            "todo_id": todo_id,
            **shared_paths,
        }
        for todo_id in ("todo-a", "todo-b")
    ]
    index_path.write_text(
        "".join(json.dumps(row) + "\n" for row in collision_rows),
        encoding="utf-8",
    )
    groups = run_index_rebuild.collision_review_groups(index_path, GOAL_ID)
    plan = run_index_rebuild.build_collision_rebuild_plan(
        groups,
        goal_filter=GOAL_ID,
        total_collision_group_count=len(groups),
        truncated=False,
    )

    rebuild_paused = threading.Event()
    allow_rebuild = threading.Event()
    append_started = threading.Event()
    append_finished = threading.Event()
    thread_errors: list[BaseException] = []
    real_write_new_or_verify = run_index_rebuild._write_new_or_verify

    def pause_before_backup(path: Path, content: str) -> None:
        if path.name.startswith("index.pre-collision-rebuild-"):
            rebuild_paused.set()
            if not allow_rebuild.wait(timeout=5):
                raise TimeoutError("test did not release the collision rebuild")
        real_write_new_or_verify(path, content)

    monkeypatch.setattr(
        run_index_rebuild,
        "_write_new_or_verify",
        pause_before_backup,
    )

    def capture_errors(operation: Any) -> None:
        try:
            operation()
        except BaseException as exc:
            thread_errors.append(exc)

    rebuild_thread = threading.Thread(
        target=lambda: capture_errors(
            lambda: run_index_rebuild.apply_reviewed_collision_rebuild(
                plan,
                plan_sha256=plan["plan_sha256"],
            )
        )
    )

    def append_run() -> None:
        append_started.set()
        history.write_reserved_run_artifacts(
            runs_dir=runs_dir,
            generated_at="2026-09-16T00:00:01+00:00",
            record={
                "goal_id": GOAL_ID,
                "generated_at": "2026-09-16T00:00:01+00:00",
            },
            index_record={
                "goal_id": GOAL_ID,
                "generated_at": "2026-09-16T00:00:01+00:00",
                "classification": "state_refreshed",
            },
            payload={"goal_id": GOAL_ID},
            render_markdown=lambda _payload: "# appended run",
        )
        append_finished.set()

    append_thread = threading.Thread(
        target=lambda: capture_errors(append_run),
    )
    rebuild_thread.start()
    assert rebuild_paused.wait(timeout=5), (
        "rebuild did not reach the pre-replace window"
    )
    append_thread.start()
    assert append_started.wait(timeout=5), "append thread did not start"
    try:
        assert not append_finished.wait(timeout=0.2), (
            "append must wait while collision rebuild owns the index"
        )
    finally:
        allow_rebuild.set()
        rebuild_thread.join(timeout=5)
        append_thread.join(timeout=5)

    assert not rebuild_thread.is_alive()
    assert not append_thread.is_alive()
    assert thread_errors == []
    rows = [
        json.loads(line)
        for line in index_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 3
    assert rows[-1]["classification"] == "state_refreshed"
