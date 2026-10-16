"""The workflow-skill install is the one authoritative writer of ``loopx/SKILL.md``.

In the Codex skills root both the workflow-skill step and the slash-command step used to
write the ``loopx`` entry skill, with different CLI paths, and the integrity readback was
recorded between them, so it never matched the installed tree.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from loopx.skill_install_readback import (
    ARK_MANAGED_AGENT_REQUIRED_SKILL_IDS,
    SKILL_INSTALL_READBACK_FILENAME,
    hash_skill_tree,
    inspect_skill_install_readback,
)
from loopx.slash_command_install import install_slash_commands
from loopx.workflow_skill_install import workflow_skill_install

REPO_ROOT = Path(__file__).resolve().parents[1]


def _codex_rows(payload: dict, command: str) -> dict[str, str]:
    return {
        row["mechanism"]: row["status"]
        for row in payload["installed"]
        if row.get("surface") == "codex" and row.get("command") == command
    }


def test_slash_commands_leave_a_workflow_owned_entry_alone(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    skills = codex_home / "skills"
    installed = workflow_skill_install(
        skills_dir=skills, execute=True, cli_bin="/opt/loopx/bin/loopx"
    )
    assert installed["ok"] is True
    entry = skills / "loopx" / "SKILL.md"
    before = entry.read_bytes()
    assert b"/opt/loopx/bin/loopx" in before

    payload = install_slash_commands(
        execute=True, surfaces=["codex"], codex_home=str(codex_home)
    )

    assert _codex_rows(payload, "/loopx")["codex_explicit_skills"] == "managed_by_workflow_skills"
    assert entry.read_bytes() == before
    assert _codex_rows(payload, "/loopx-global-summary")["codex_explicit_skills"] == "created"

    removed = install_slash_commands(
        execute=True, uninstall=True, surfaces=["codex"], codex_home=str(codex_home)
    )

    rows = _codex_rows(removed, "/loopx")
    assert rows["codex_explicit_skills"] == "managed_by_workflow_skills"
    assert rows["codex_skill_openai_metadata"] == "managed_by_workflow_skills"
    assert entry.read_bytes() == before


def _node_at_least(major: int, minor: int) -> bool:
    node = shutil.which("node")
    if not node:
        return False
    version = subprocess.run([node, "--version"], capture_output=True, text=True).stdout
    try:
        found = tuple(int(part) for part in version.strip().lstrip("v").split(".")[:2])
    except ValueError:
        return False
    return found >= (major, minor)


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None or not _node_at_least(22, 6),
    reason="scripts/install-local.sh needs POSIX bash and Node.js >= 22.6",
)
def test_repeated_install_local_keeps_an_accurate_readback_without_backups(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "CODEX_HOME": str(home / ".codex"),
        "LOOPX_PROMOTE_DEFAULT": "1",
        "LOOPX_INSTALL_CANARY": "0",
        "LOOPX_INSTALL_SLASH_COMMAND_SURFACES": "codex",
        "LOOPX_SHELL_PROFILE": str(home / ".profile"),
    }
    skills = home / ".codex" / "skills"

    for attempt in (1, 2):
        result = subprocess.run(
            ["bash", str(REPO_ROOT / "scripts" / "install-local.sh")],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=900,
        )
        assert result.returncode == 0, (attempt, result.stdout[-3000:], result.stderr[-3000:])

        readback = inspect_skill_install_readback(
            skills_dir=skills, required_skill_ids=ARK_MANAGED_AGENT_REQUIRED_SKILL_IDS
        )
        assert readback["ready"] is True, (attempt, readback["reason"])
        manifest = json.loads((skills / SKILL_INSTALL_READBACK_FILENAME).read_text(encoding="utf-8"))
        for skill_id in ARK_MANAGED_AGENT_REQUIRED_SKILL_IDS:
            assert manifest["skills"]["items"][skill_id]["sha256"] == hash_skill_tree(
                skills / skill_id
            )["sha256"], (attempt, skill_id)
        entry = (skills / "loopx" / "SKILL.md").read_text(encoding="utf-8")
        assert str(home / ".local" / "bin" / "loopx") in entry
        assert (skills / "loopx" / "agents" / "openai.yaml").is_file()
        assert not list(home.rglob(".loopx-skill-backups")), attempt
