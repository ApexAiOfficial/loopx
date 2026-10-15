from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.skill_install_readback import (
    SKILL_BACKUP_DIR_ENV,
    SKILL_BACKUP_DIRNAME,
    hash_skill_tree,
    retire_skill_dir,
)


@pytest.fixture(autouse=True)
def _no_backup_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SKILL_BACKUP_DIR_ENV, raising=False)


def _skill(skills_dir: Path, name: str = "loopx-project") -> Path:
    path = skills_dir / name
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(f"# {name}\n\nInstalled body.\n", encoding="utf-8")
    return path


def test_unchanged_install_output_is_deleted(tmp_path: Path) -> None:
    skills_dir = tmp_path / ".agents" / "skills"
    path = _skill(skills_dir)
    recorded = hash_skill_tree(path)["sha256"]

    outcome = retire_skill_dir(path, skills_dir=skills_dir, recorded_hash=recorded, reason="test")

    assert outcome["action"] == "deleted_pristine"
    assert not path.exists()
    assert not (tmp_path / ".agents" / SKILL_BACKUP_DIRNAME).exists()


def test_edited_copy_is_moved_beside_the_skills_root_with_a_note(tmp_path: Path) -> None:
    skills_dir = tmp_path / ".agents" / "skills"
    path = _skill(skills_dir)
    recorded = hash_skill_tree(path)["sha256"]
    (path / "SKILL.md").write_text("# loopx-project\n\nuser edit\n", encoding="utf-8")

    outcome = retire_skill_dir(path, skills_dir=skills_dir, recorded_hash=recorded, reason="test")

    assert outcome["action"] == "backed_up"
    assert not path.exists()
    backup = Path(outcome["backup"])
    assert backup.parent.parent.parent == tmp_path / ".agents" / SKILL_BACKUP_DIRNAME
    assert backup.parent.name == "agents-skills"
    assert "user edit" in (backup / "SKILL.md").read_text(encoding="utf-8")
    note = json.loads(backup.with_name(backup.name + ".loopx-retired.json").read_text(encoding="utf-8"))
    assert note["original_path"] == str(skills_dir / "loopx-project")
    assert note["recorded_sha256"] == recorded


def test_unrecorded_copy_and_symlink_are_moved_never_followed(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    unrecorded = _skill(skills_dir, "loopx-benchmark")
    linked_source = _skill(tmp_path / "dev", "loopx-pr-review")
    link = skills_dir / "loopx-pr-review"
    link.symlink_to(linked_source, target_is_directory=True)

    first = retire_skill_dir(unrecorded, skills_dir=skills_dir, recorded_hash=None, reason="test")
    second = retire_skill_dir(
        link,
        skills_dir=skills_dir,
        recorded_hash=hash_skill_tree(linked_source)["sha256"],
        reason="test",
    )

    assert first["action"] == second["action"] == "backed_up"
    assert not unrecorded.exists() and not link.is_symlink()
    assert Path(second["backup"]).is_symlink()
    assert (linked_source / "SKILL.md").is_file()


def test_backup_root_can_be_overridden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SKILL_BACKUP_DIR_ENV, str(tmp_path / "kept"))
    skills_dir = tmp_path / "skills"
    path = _skill(skills_dir)

    outcome = retire_skill_dir(path, skills_dir=skills_dir, recorded_hash=None, reason="test")

    assert Path(outcome["backup"]).is_relative_to(tmp_path / "kept")
