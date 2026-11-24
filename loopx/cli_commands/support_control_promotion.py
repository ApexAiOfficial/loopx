"""Registration and dispatch for the promotion-gate, promotion-readiness, and
upgrade-plan commands.

Refs GH-C06. This group was carved out of `support_control.py`, which registers
seven unrelated top-level commands in one module that sits just under the
1000-line default budget in
`examples/cli-command-module-size-ownership-command-modularization-smoke.py`.
The three commands are one group -- canary promotion readiness and the local
default upgrade plan that follows it -- so their parser flags and their
dispatch branches move together and the public invocation is unchanged.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from ..promotion_gate import (
    build_promotion_gate,
    record_promotion_readiness,
    render_promotion_gate_markdown,
    render_promotion_readiness_record_markdown,
)
from ..upgrade import build_upgrade_plan, render_upgrade_plan_markdown

PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]

PROMOTION_CONTROL_COMMANDS = {
    "promotion-gate",
    "promotion-readiness",
    "upgrade-plan",
}


def register_promotion_control_commands(
    subparsers: argparse._SubParsersAction,
    add_subcommand_format: Callable[[argparse.ArgumentParser], None],
) -> None:
    promotion_gate_parser = subparsers.add_parser(
        "promotion-gate",
        help="Emit a compact machine-readable canary promotion readiness gate result.",
    )
    add_subcommand_format(promotion_gate_parser)

    promotion_readiness_parser = subparsers.add_parser(
        "promotion-readiness",
        help="Record release-scoped canary promotion-readiness evidence.",
    )
    promotion_readiness_subparsers = promotion_readiness_parser.add_subparsers(
        dest="promotion_readiness_command",
        required=True,
    )
    promotion_readiness_record_parser = promotion_readiness_subparsers.add_parser(
        "record",
        help="Append one runtime-level readiness event after the canary checks pass.",
    )
    add_subcommand_format(promotion_readiness_record_parser)
    promotion_readiness_record_parser.add_argument(
        "--dashboard-readiness",
        choices=("passed", "skipped"),
        required=True,
        help="Whether dashboard readiness ran successfully or was explicitly skipped.",
    )
    promotion_readiness_record_parser.add_argument(
        "--execute",
        action="store_true",
        help="Append the evidence event. Without this flag, emit a dry-run plan.",
    )

    upgrade_plan_parser = subparsers.add_parser(
        "upgrade-plan",
        help="Plan local default upgrade propagation for managed heartbeat automations.",
    )
    add_subcommand_format(upgrade_plan_parser)
    upgrade_plan_parser.add_argument(
        "--goal-id",
        action="append",
        default=[],
        help="Only include one goal id. Repeatable.",
    )
    upgrade_plan_parser.add_argument(
        "--installed-manifest",
        help=(
            "Optional JSON manifest of installed automations with goal_id, mode, automation_id, and "
            "prompt_sha256/task_body. If omitted, upgrade-plan auto-discovers Codex App heartbeat "
            "automations from $CODEX_HOME/automations or ~/.codex/automations."
        ),
    )
    upgrade_plan_parser.add_argument(
        "--cli-bin",
        default="loopx",
        help="CLI command embedded in generated heartbeat prompts for the promoted default.",
    )
    upgrade_plan_parser.add_argument(
        "--mode",
        action="append",
        choices=["thin", "brief", "compact"],
        default=[],
        help="Prompt mode to compare. Repeatable; defaults to the thin installed heartbeat contract.",
    )

def handle_promotion_control_command(
    args: argparse.Namespace,
    *,
    registry_path: Path,
    print_payload: PrintPayload,
    output_format: Callable[[argparse.Namespace], str],
) -> int | None:
    if args.command not in PROMOTION_CONTROL_COMMANDS:
        return None

    if args.command == "promotion-gate":
        try:
            payload = build_promotion_gate(
                registry_path=registry_path,
                runtime_root_override=args.runtime_root,
            )
        except Exception as exc:
            payload = {
                "ok": False,
                "registry": str(registry_path),
                "runtime_root": args.runtime_root,
                "gate": "promotion_readiness",
                "gate_state": "error",
                "can_promote": False,
                "should_warn": True,
                "non_blocking": True,
                "error": str(exc),
                "recommended_action": "fix promotion readiness gate collection before promotion",
            }
        print_payload(payload, output_format(args), render_promotion_gate_markdown)
        return 0 if payload.get("ok") else 1

    if args.command == "promotion-readiness":
        try:
            payload = record_promotion_readiness(
                registry_path=registry_path,
                runtime_root_override=args.runtime_root,
                dashboard_readiness=args.dashboard_readiness,
                execute=args.execute,
            )
        except Exception as exc:
            payload = {
                "ok": False,
                "dry_run": not args.execute,
                "appended": False,
                "registry": str(registry_path),
                "runtime_root": args.runtime_root,
                "evidence_scope": "runtime_release",
                "error": str(exc),
            }
        print_payload(
            payload,
            output_format(args),
            render_promotion_readiness_record_markdown,
        )
        return 0 if payload.get("ok") else 1

    if args.command == "upgrade-plan":
        try:
            payload = build_upgrade_plan(
                registry_path=registry_path,
                runtime_root_override=args.runtime_root,
                installed_manifest=Path(args.installed_manifest).expanduser()
                if args.installed_manifest
                else None,
                cli_bin=args.cli_bin,
                modes=args.mode or None,
                goal_ids=args.goal_id or None,
            )
        except Exception as exc:
            payload = {
                "ok": False,
                "mode": "upgrade-plan",
                "registry": str(registry_path),
                "runtime_root": args.runtime_root,
                "error": str(exc),
                "summary": {
                    "managed_goal_count": 0,
                    "current_prompt_count": 0,
                    "stale_prompt_count": 0,
                    "unknown_prompt_count": 0,
                    "not_installed_prompt_count": 0,
                    "stage_deferred_goal_count": 0,
                    "ready_for_default_promotion": False,
                    "installed_manifest_available": False,
                    "installed_manifest_source": None,
                    "installed_manifest_entry_count": 0,
                    "installed_manifest_task_body_count": 0,
                    "installed_manifest_has_task_body": False,
                },
                "recommended_action": "fix upgrade-plan collection before default promotion",
            }
        print_payload(payload, output_format(args), render_upgrade_plan_markdown)
        return 0 if payload.get("ok") else 1

    return None
