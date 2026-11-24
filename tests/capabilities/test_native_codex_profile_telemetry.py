"""Synthetic profile environments never contribute adoption telemetry."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from loopx.capabilities.benchmark_toolkit.native_codex_profile import (
    _formal_install_environment,
    native_codex_app_server_shell_policy_args,
    native_codex_profile_environment,
)


def profile_environments(root, base):
    paths = {key: root / key for key in (
        "home", "codex_home", "bin_dir", "release_root", "man_root", "shell_profile", "skills_dir",
    )}
    return [
        _formal_install_environment(paths=paths, python_executable=sys.executable,
                                    release_id="fixture", base_env=base),
        native_codex_profile_environment(SimpleNamespace(**paths), base_env=base),
    ]


@pytest.mark.parametrize("base", [{}, {"CI": "true"}, {"LOOPX_USAGE_PING": "1"},
                                  {"DO_NOT_TRACK": "1", "LOOPX_USAGE_PING": "0"}])
def test_install_and_runtime_environments_disable_even_without_inherited_ci(tmp_path, base):
    for env in profile_environments(tmp_path, base):
        assert env.get("LOOPX_USAGE_PING") == "0"


def test_agent_shell_reconstruction_explicitly_disables_telemetry():
    arguments = native_codex_app_server_shell_policy_args(excluded_env_keys=("RUNNER_SENTINEL",))
    policy = tomllib.loads("\n".join(arguments[1::2]))["shell_environment_policy"]
    assert policy["set"]["LOOPX_USAGE_PING"] == "0"
    assert "RUNNER_SENTINEL" in policy["exclude"]
    # The explicit override survives even if the shell inherits no parent keys.
    result = subprocess.run([sys.executable, "-c", "import os; print(os.environ['LOOPX_USAGE_PING'])"],
                            env=policy["set"], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "0"


def test_profile_cli_and_typed_sender_cannot_override_disabled_collection(tmp_path):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(self.path)
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        env = profile_environments(tmp_path, {"PATH": os.environ["PATH"], "LOOPX_USAGE_PING": "1"})[1]
        # Any regression is contained by a disposable collector, never production.
        env["LOOPX_USAGE_PING_ENDPOINT"] = f"http://127.0.0.1:{server.server_port}/v1/ping"
        code = '''
import json
from loopx import usage_ping
from loopx.cli_runtime import main
enabled = usage_ping.control("enable")
assert enabled["blocked_by"] == "LOOPX_USAGE_PING"
assert not enabled["sending"]
assert main(["version", "--format", "json"]) == 0
assert main(["version", "--format", "json"]) == 0
state = json.loads(usage_ping.state_path().read_text())
for action, fields in [("start", {}), ("observe", dict(feature="todo", outcome="ok", error="none", elapsed_ms=1))]:
    result = usage_ping.control(action, generation=state["generation"], **fields)
    assert result == {"sent": False, "reason": "blocked"}
after = json.loads(usage_ping.state_path().read_text())
assert after == state
assert "last_attempt_day" not in after and "counters" not in after
'''
        result = subprocess.run([sys.executable, "-c", code], env=env,
                                cwd=Path(__file__).resolve().parents[2],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert requests == []
    finally:
        server.shutdown()
        server.server_close()
