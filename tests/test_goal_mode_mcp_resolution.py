"""Regression tests for MCP CLI resolution and list_todos semantics."""
from __future__ import annotations

import sys
from pathlib import Path

from loopx.goal_mode_mcp import GoalModeMCPConfig, GoalModeMCPControlPlane

CONFIG = GoalModeMCPConfig(
    server_name="loopx",
    runtime_profile="generic_cli",
    legacy_host_surface="generic_cli",
    setup_hint="run loopx connect first",
)


def _plane(context=None):
    return GoalModeMCPControlPlane(CONFIG, lambda: context or {})


def test_loopx_bin_override_wins(tmp_path, monkeypatch):
    exe = tmp_path / "loopx"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setenv("LOOPX_BIN", str(exe))
    assert _plane().command_prefix() == [str(exe)]


def test_falls_back_to_user_local_when_path_misses(tmp_path, monkeypatch):
    """A GUI-launched server often has no ~/.local/bin on PATH."""
    monkeypatch.delenv("LOOPX_BIN", raising=False)
    monkeypatch.setattr("loopx.goal_mode_mcp.shutil.which", lambda _n: None)
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    exe = home / ".local" / "bin" / "loopx"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
    assert _plane().command_prefix() == [str(exe)]


def test_module_fallback_is_last_resort(tmp_path, monkeypatch):
    monkeypatch.delenv("LOOPX_BIN", raising=False)
    monkeypatch.setattr("loopx.goal_mode_mcp.shutil.which", lambda _n: None)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path / "empty"))
    assert _plane().command_prefix() == [sys.executable, "-m", "loopx.cli"]


def test_list_todos_lists_todos_rather_than_the_quota_decision():
    """It must invoke `todo list`, not the should-run path: a quota decision
    carries no todo_id, which claim_task and complete_task both require."""
    plane = _plane({"goal_id": "g1", "registry": "/tmp/registry.json"})
    seen: list[list[str]] = []
    plane.run_cli = lambda args, **kw: seen.append(args) or "{}"  # type: ignore[assignment]
    plane.list_todos()
    assert seen, "list_todos issued no CLI call"
    assert "todo" in seen[0] and "list" in seen[0], seen[0]
    assert "should-run" not in seen[0], seen[0]


def test_list_todos_without_a_goal_reports_setup_hint():
    assert "loopx connect" in _plane().list_todos()
