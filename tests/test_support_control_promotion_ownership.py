"""Refs GH-C06: the promotion command group still belongs to support control.

`promotion-gate`, `promotion-readiness`, and `upgrade-plan` were extracted from
`cli_commands/support_control.py` into
`cli_commands/support_control_promotion.py` so the shared support-control seam
stops owning three unrelated command groups at once. The extraction must not
change the public invocation, so these cases pin the two things that could
silently break it: the commands must still be part of the support control set,
and each must still be registered exactly once.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from loopx.cli_commands import support_control
from loopx.cli_commands import support_control_promotion as promotion_module

COMMANDS_DIR = Path(promotion_module.__file__).resolve().parent
ADD_PARSER_RE = re.compile(
    r"subparsers\.add_parser\(\s*(?:\n\s*)?[\"'](?P<command>[^\"']+)[\"']",
    re.MULTILINE,
)

PROMOTION_COMMANDS = ("promotion-gate", "promotion-readiness", "upgrade-plan")


def registered_commands() -> dict[str, list[str]]:
    registrations: dict[str, list[str]] = {}
    for path in sorted(COMMANDS_DIR.glob("*.py")):
        for match in ADD_PARSER_RE.finditer(path.read_text(encoding="utf-8")):
            registrations.setdefault(match.group("command"), []).append(path.name)
    return registrations


def test_promotion_commands_are_still_support_control_commands() -> None:
    for command in PROMOTION_COMMANDS:
        assert command in support_control.SUPPORT_CONTROL_COMMANDS


def test_promotion_commands_are_registered_exactly_once() -> None:
    registrations = registered_commands()
    for command in PROMOTION_COMMANDS:
        assert registrations[command] == ["support_control_promotion.py"]


def test_owner_module_exposes_both_halves() -> None:
    """Registration and dispatch moved together, so both live in the new module."""
    assert callable(promotion_module.register_promotion_control_commands)
    assert callable(promotion_module.handle_promotion_control_command)


def test_owner_module_owns_exactly_its_group() -> None:
    assert promotion_module.PROMOTION_CONTROL_COMMANDS == set(PROMOTION_COMMANDS)


def test_dispatch_ignores_other_commands() -> None:
    """A non-promotion command must fall through untouched, before any work."""
    args = argparse.Namespace(command="update")
    assert (
        promotion_module.handle_promotion_control_command(
            args,
            registry_path=Path("/nonexistent-registry"),
            print_payload=lambda *_args: None,
            output_format=lambda *_args: "json",
        )
        is None
    )
