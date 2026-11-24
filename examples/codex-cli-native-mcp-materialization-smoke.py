#!/usr/bin/env python3
"""Prove a fresh real Codex Turn can call an invocation-bound MCP tool."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import uuid


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.control_plane.turn_driver.codex_cli import (  # noqa: E402
    CODEX_STDIO_MCP_SERVER_SCHEMA_VERSION,
    run_codex_cli_host,
)


def _request() -> dict[str, object]:
    return {
        "schema_version": "loopx_turn_host_request_v0",
        "turn_key": "sha256:" + "a" * 64,
        "route": "ready_for_host",
        "session": {
            "schema_version": "loopx_turn_session_binding_v0",
            "action": "start_new",
        },
        "turn_envelope": {
            "schema_version": "loopx_turn_envelope_v0",
            "goal_id": "native-mcp-materialization",
            "agent_id": "native-mcp-worker",
            "action": {
                "selected_todo": {
                    "todo_id": "todo_native_mcp_materialization",
                    "text": (
                        "Call the native MCP tool read_bound_identity. Do not use "
                        "shell or infer its result. Return validated_progress and "
                        "include the exact nonce returned by the tool in summary."
                    ),
                }
            },
        },
        "result_contract": {
            "schema_version": "loopx_turn_result_v0",
            "completed_phases": ["host_execute", "typed_result"],
        },
    }


def _server(path: Path, nonce: str) -> None:
    path.write_text(
        "\n".join(
            [
                "from mcp.server.fastmcp import FastMCP",
                'server = FastMCP("loopx-native-proof")',
                "@server.tool()",
                "def read_bound_identity():",
                '    \"\"\"Read the host-bound identity and proof nonce.\"\"\"',
                "    return "
                + repr(
                    {
                        "goal_id": "native-mcp-materialization",
                        "agent_id": "native-mcp-worker",
                        "nonce": nonce,
                    }
                ),
                'if __name__ == "__main__":',
                '    server.run(transport="stdio")',
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--model")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument(
        "--real-codex-cli",
        action="store_true",
        help="Run the live Codex CLI check instead of recording a default skip.",
    )
    args = parser.parse_args()
    if not args.real_codex_cli:
        print(
            json.dumps(
                {
                    "ok": True,
                    "skipped": True,
                    "reason": "real Codex CLI execution requires --real-codex-cli",
                },
                indent=2,
            )
        )
        return 0
    codex_bin = shutil.which(args.codex_bin)
    if codex_bin is None:
        parser.error(f"Codex CLI is unavailable: {args.codex_bin}")

    nonce = "native-mcp-" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="loopx-native-mcp-") as raw:
        root = Path(raw)
        project = root / "project"
        project.mkdir()
        server = root / "server.py"
        _server(server, nonce)
        result = run_codex_cli_host(
            _request(),
            runtime_root=root / "runtime",
            project=project,
            codex_bin=codex_bin,
            sandbox="read-only",
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            mcp_server={
                "schema_version": CODEX_STDIO_MCP_SERVER_SCHEMA_VERSION,
                "name": "loopx_native_proof",
                "command": [sys.executable, str(server)],
            },
            timeout_seconds=args.timeout_seconds,
        )
    assert result["result_kind"] == "validated_progress", result
    assert nonce in result["summary"], result
    print(
        json.dumps(
            {
                "ok": True,
                "result_kind": result["result_kind"],
                "native_tool_proof": True,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
