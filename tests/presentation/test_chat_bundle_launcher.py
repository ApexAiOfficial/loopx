"""The npm Chat build entry resolves an interpreter instead of assuming python3.

Supported Windows installations often expose `python.exe` only, and a
`python3.exe` App Execution Alias stub is not runnable. The npm entry must still
reach the shared builder, so interpreter resolution is exercised here and on
native Windows CI.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts/chat_bundle_launcher.mjs"
NODE = shutil.which("node")
POSIX_SHIMS = os.name != "nt"

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js runs this npm entry")


def checkout(tmp_path: Path) -> Path:
    """A disposable checkout holding the launcher and a witness builder."""
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    shutil.copyfile(LAUNCHER, root / "scripts/chat_bundle_launcher.mjs")
    (root / "scripts/chat_bundle.py").write_text(
        "import sys\n"
        "print('builder:' + sys.executable)\n"
        "print('argv:' + ' '.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    return root


def shim(path: Path, witness: Path, *, label: str, compatible: bool) -> None:
    """A POSIX stand-in interpreter that records when it runs the builder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if compatible:
        body = (
            'for argument in "$@"; do\n'
            '  case "$argument" in\n'
            f"    *chat_bundle.py) echo {shlex.quote(label)}"
            f" >> {shlex.quote(str(witness))};;\n"
            "  esac\n"
            "done\n"
            f'exec {shlex.quote(sys.executable)} "$@"'
        )
    else:
        body = "exit 9009"
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def environment(path_dirs: list[Path], **extra: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key != "LOOPX_PYTHON"}
    env["PATH"] = os.pathsep.join(str(item) for item in path_dirs)
    env.update(extra)
    return env


def run(root: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [NODE, str(root / "scripts/chat_bundle_launcher.mjs"), *args],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )


@pytest.mark.skipif(not POSIX_SHIMS, reason="POSIX shim interpreter")
def test_python_exe_only_path_still_reaches_the_builder(tmp_path):
    root = checkout(tmp_path)
    witness = tmp_path / "witness"
    shims = tmp_path / "bin"
    shim(shims / "python3", witness, label="python3", compatible=False)
    shim(shims / "python", witness, label="python", compatible=True)
    env = environment([shims])
    # The environment that used to break the npm entry: no usable python3.
    legacy = subprocess.run(
        ["/bin/sh", "-c", f"python3 {root / 'scripts/chat_bundle.py'} build"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert legacy.returncode != 0
    result = run(root, env, "build")
    assert result.returncode == 0, result.stderr
    assert witness.read_text().split() == ["python"]
    assert "argv:build" in result.stdout


@pytest.mark.skipif(not POSIX_SHIMS, reason="POSIX shim interpreter")
def test_recorded_and_explicit_interpreters_precede_path_discovery(tmp_path):
    root = checkout(tmp_path)
    witness = tmp_path / "witness"
    shims = tmp_path / "bin"
    shim(shims / "python3", witness, label="path", compatible=True)
    shim(root / ".venv/bin/python", witness, label="venv", compatible=True)
    recorded = tmp_path / "recorded/bin/python"
    shim(recorded, witness, label="recorded", compatible=True)
    (root / ".loopx-python").write_text(str(recorded) + "\n", encoding="utf-8")
    assert run(root, environment([shims])).returncode == 0
    explicit = tmp_path / "explicit/bin/python"
    shim(explicit, witness, label="explicit", compatible=True)
    assert (
        run(root, environment([shims], LOOPX_PYTHON=str(explicit))).returncode == 0
    )
    assert witness.read_text().split() == ["recorded", "explicit"]


@pytest.mark.skipif(not POSIX_SHIMS, reason="POSIX shim interpreter")
def test_unusable_explicit_interpreter_does_not_fall_back(tmp_path):
    root = checkout(tmp_path)
    witness = tmp_path / "witness"
    shims = tmp_path / "bin"
    shim(shims / "python3", witness, label="path", compatible=True)
    result = run(
        root,
        environment([shims], LOOPX_PYTHON=str(tmp_path / "missing-python")),
    )
    assert result.returncode == 2
    assert "LOOPX_PYTHON" in result.stderr
    assert not witness.exists()


@pytest.mark.skipif(not POSIX_SHIMS, reason="POSIX shim interpreter")
def test_missing_interpreter_reports_the_npm_entry_to_rerun(tmp_path):
    root = checkout(tmp_path)
    witness = tmp_path / "witness"
    shims = tmp_path / "bin"
    shim(shims / "python3", witness, label="python3", compatible=False)
    result = run(root, environment([shims]))
    assert result.returncode == 2
    assert "Python 3.11+" in result.stderr
    assert "npm run build:chat" in result.stderr
    assert not witness.exists()


def test_npm_entry_uses_the_portable_launcher():
    scripts = json.loads(
        (ROOT / "apps/presentation/dashboard/package.json").read_text(encoding="utf-8")
    )["scripts"]
    assert scripts["build:chat"] == "node ../../../scripts/chat_bundle_launcher.mjs build"
    assert "python3" not in scripts["build:chat"]
    assert scripts["build"].endswith("&& npm run build:chat")
    # The launcher only selects an interpreter; build rules stay in the builder.
    launcher = LAUNCHER.read_text(encoding="utf-8")
    assert '"scripts", "chat_bundle.py"' in launcher
    assert "build:chat:vite" not in launcher
