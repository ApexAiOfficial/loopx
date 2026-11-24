"""Explicit refresh-state capture wrapper plus a separate bounded consumer."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable

from .config import load_config, strict_json


def _refresh_command(args: list[str]) -> bool:
    """Inspect the command position, never an arbitrary argument's text."""
    index = 0
    while index < len(args) and args[index].startswith("--"):
        option, separator, value = args[index].partition("=")
        if option not in {"--registry", "--runtime-root", "--format"}:
            return False
        if separator:
            if not value:
                return False
            index += 1
        else:
            if index + 1 >= len(args):
                return False
            index += 2
    return args[index : index + 1] == ["refresh-state"]


def refresh(
    argv: list[str],
    root: Path,
    config_path: Path | None,
    invoke: Callable[[list[str]], int],
) -> int:
    """Preserve the original exit code/stdout; never infer inside its transaction."""
    args = list(argv)
    if args[:1] == ["--"]:
        args.pop(0)
    if args[:1] == ["loopx"]:
        args.pop(0)
    prepared = None
    failure = None
    started = time.perf_counter_ns()
    try:
        config = load_config(config_path)
        if config.mode == "off" or "--dry-run" in args:
            return invoke(args)
        if config_path is None or not _refresh_command(args):
            raise ValueError("requires_refresh_state")
        from .drift import prepare

        prepared = prepare(root, config_path)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
    ):
        failure = "capture_preparation_failed"
    prepared_at = time.perf_counter_ns()
    output = io.StringIO()
    with redirect_stdout(output):
        code = invoke(args)
    owner_finished = time.perf_counter_ns()
    sys.stdout.write(output.getvalue())
    diagnostic: dict[str, Any] = {"status": "not_captured", "reason": failure}
    # No output of an unsuccessful core command is interpreted as a work event.
    if code == 0:
        try:
            receipt = strict_json(output.getvalue())
            if not isinstance(receipt, dict) or receipt.get("dry_run") is True:
                raise ValueError("requires_json_refresh_receipt")
            if receipt.get("appended") is not True or not receipt.get("json_path"):
                diagnostic = {"status": "no_new_run"}
            elif prepared is not None:
                from .drift import enqueue

                diagnostic = enqueue(
                    root,
                    prepared,
                    Path(receipt["json_path"]),
                    prepare_ns=prepared_at - started,
                    owner_command_ns=owner_finished - prepared_at,
                )
            else:
                raise ValueError("capture_was_unavailable")
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            RuntimeError,
            subprocess.SubprocessError,
        ):
            diagnostic = {
                "status": "capture_failed",
                "reason": failure or "evidence_or_receipt_unavailable",
            }
            try:
                from .drift import invalidate_baseline

                invalidate_baseline(root)
            except (OSError, ValueError, KeyError, TypeError):
                diagnostic["baseline_reset"] = "unavailable"
    diagnostic["timing_ns"] = {
        "prepare": prepared_at - started,
        "owner_command": owner_finished - prepared_at,
        "post_commit_capture": time.perf_counter_ns() - owner_finished,
    }
    diagnostic.update(authority="none", model_called=False)
    print(json.dumps({"jev_drift": diagnostic}), file=sys.stderr)
    return code


def register(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser(
        "drift", help="Optional task-progress observation; never steer or pause"
    )
    operations = parser.add_subparsers(dest="drift_command", required=True)
    init = operations.add_parser(
        "init", help="bind a Goal, scoped files, and an initial baseline"
    )
    init.add_argument("--state-dir", type=Path, required=True)
    init.add_argument("--config", type=Path, required=True)
    init.add_argument("--workspace", type=Path, required=True)
    init.add_argument("--basis", type=Path, required=True)
    init.add_argument("--path", dest="paths", action="append", required=True)
    init.add_argument(
        "--runtime-root",
        type=Path,
        help=(
            "LoopX runtime root. When given, one typed receipt per evaluated "
            "event is written under goals/<goal-id>/progress-review/receipts for "
            "the core progress-review policy to read."
        ),
    )
    wrap = operations.add_parser(
        "refresh", help="capture around the actual refresh-state command; no inference"
    )
    wrap.add_argument("--state-dir", type=Path, required=True)
    wrap.add_argument("--config", type=Path)
    wrap.add_argument("args", nargs=argparse.REMAINDER)
    consume = operations.add_parser(
        "drain", help="evaluate captured immutable jobs in a separate process"
    )
    consume.add_argument("--state-dir", type=Path, required=True)
    consume.add_argument("--config", type=Path)
    consume.add_argument("--watch-seconds", type=float, default=0)
    consume.add_argument("--poll-ms", type=int, default=1000)
    read = operations.add_parser(
        "status",
        help="read results, unknowns and capture failures without raw evidence",
    )
    read.add_argument("--state-dir", type=Path, required=True)
    settings = operations.add_parser(
        "configure", help="switch this local Goal observer off or shadow"
    )
    settings.add_argument("--state-dir", type=Path, required=True)
    settings.add_argument("--mode", choices=["off", "shadow"], required=True)
    truth = operations.add_parser(
        "label", help="record a private human truth label for one observed event"
    )
    truth.add_argument("--state-dir", type=Path, required=True)
    truth.add_argument("--event-id", required=True)
    truth.add_argument("--truth", choices=["drift", "on_goal", "unknown"], required=True)
    truth.add_argument("--note", default="")


def run(parsed: argparse.Namespace, invoke: Callable[[list[str]], int]) -> int:
    if parsed.drift_command == "refresh":
        return refresh(parsed.args, parsed.state_dir, parsed.config, invoke)
    if (
        parsed.drift_command in {"init", "drain"}
        and load_config(parsed.config).mode == "off"
    ):
        print(json.dumps({"status": "disabled"}))
        return 0
    from .drift import configure, drain, initialize, label, status

    if parsed.drift_command == "init":
        result = initialize(
            parsed.state_dir,
            parsed.workspace,
            parsed.basis,
            parsed.config,
            parsed.paths,
            runtime_root=parsed.runtime_root,
        )
    elif parsed.drift_command == "label":
        result = label(parsed.state_dir, parsed.event_id, parsed.truth, parsed.note)
    elif parsed.drift_command == "configure":
        result = configure(parsed.state_dir, parsed.mode)
    elif parsed.drift_command == "status":
        result = status(parsed.state_dir)
    else:
        if not 0 <= parsed.watch_seconds <= 3600 or not 100 <= parsed.poll_ms <= 60000:
            raise ValueError("invalid_consumer_poll_budget")
        deadline = time.monotonic() + parsed.watch_seconds
        while True:
            result = drain(parsed.state_dir, parsed.config)
            if result["status"] == "disabled" or time.monotonic() >= deadline:
                break
            print(json.dumps(result), flush=True)
            time.sleep(min(parsed.poll_ms / 1000, max(0, deadline - time.monotonic())))
    print(json.dumps(result))
    return 0
