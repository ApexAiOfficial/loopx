"""Content-addressed completion result objects install atomically and recover."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from loopx.control_plane.todos.completion_result import store_completion_result


def _store(tmp_path: Path, text: str) -> dict:
    source = tmp_path / "result.md"
    source.write_text(text, encoding="utf-8")
    return store_completion_result(source=source, runtime_root=tmp_path / "runtime", goal_id="goal")


def _object_path(tmp_path: Path, digest: str) -> Path:
    return tmp_path / "runtime" / "goals" / "goal" / "result-objects" / digest


def test_store_installs_complete_bytes_and_is_idempotent(tmp_path: Path) -> None:
    text = "# Accepted report\n\nComplete bytes.\n"
    first = _store(tmp_path, text)
    target = _object_path(tmp_path, first["sha256"])
    assert target.read_text(encoding="utf-8") == text
    assert not list(target.parent.glob("*.tmp"))
    second = _store(tmp_path, text)
    assert second == first
    assert target.read_text(encoding="utf-8") == text


def test_interrupted_object_is_replaced_by_a_complete_retry(tmp_path: Path) -> None:
    text = "# Accepted report\n\nComplete bytes.\n"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    target = _object_path(tmp_path, digest)
    target.parent.mkdir(parents=True, exist_ok=True)
    # The artifact of an interrupted legacy store: a partial file at the final
    # digest path, which used to make every later retry fail.
    target.write_bytes(text.encode("utf-8")[:6])
    stored = _store(tmp_path, text)
    assert stored["sha256"] == digest
    assert target.read_text(encoding="utf-8") == text
    assert not list(target.parent.glob("*.tmp"))


def test_object_install_never_writes_through_a_link(tmp_path: Path) -> None:
    text = "# Accepted report\n\nComplete bytes.\n"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    target = _object_path(tmp_path, digest)
    target.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.md"
    outside.write_text("untouched\n", encoding="utf-8")
    target.symlink_to(outside)
    stored = _store(tmp_path, text)
    assert stored["sha256"] == digest
    assert not target.is_symlink()
    assert target.read_text(encoding="utf-8") == text
    assert outside.read_text(encoding="utf-8") == "untouched\n"


def test_store_rejects_an_oversized_or_empty_source(tmp_path: Path) -> None:
    empty = tmp_path / "empty.md"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="1\\.\\.128000 bytes"):
        store_completion_result(source=empty, runtime_root=tmp_path / "runtime", goal_id="goal")
