from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from ..control_plane.goals.operator_actions import (
    GOAL_ACTION_CATALOG_SCHEMA_VERSION,
    build_goal_action_catalog,
    render_goal_action_catalog_markdown,
)


PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]


def register_goal_actions_command(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "goal-actions",
        help="List fresh typed owner actions for one Goal.",
    )
    parser.add_argument(
        "--goal-id", required=True, help="Goal id present in the active registry."
    )


def handle_goal_actions_command(
    args: argparse.Namespace,
    *,
    registry_path: Path,
    print_payload: PrintPayload,
) -> int:
    try:
        payload = build_goal_action_catalog(
            registry_path=registry_path,
            goal_id=args.goal_id,
            runtime_root_override=args.runtime_root,
        )
    except Exception as exc:
        payload = {
            "ok": False,
            "schema_version": GOAL_ACTION_CATALOG_SCHEMA_VERSION,
            "goal_id": args.goal_id,
            "actions": [],
            "error": str(exc),
        }
    print_payload(payload, args.format, render_goal_action_catalog_markdown)
    return 0 if payload.get("ok") else 1
