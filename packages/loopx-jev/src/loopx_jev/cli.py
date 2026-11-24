"""Optional historical progress observations; no Agent control commands."""

from __future__ import annotations
import argparse
import json
import sys
from .drift_cli import register, run
from .sentinel_cli import register as register_sentinel, run as run_sentinel


def _original(argv: list[str]) -> int:
    from loopx.entrypoint import main as core_main

    return core_main(argv)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    register(commands)
    register_sentinel(commands)
    args = parser.parse_args(argv)
    try:
        if args.command == "sentinel":
            return run_sentinel(args)
        return run(args, _original)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "reason": "invalid_configuration_or_local_evidence",
                }
            ),
            file=sys.stderr,
        )
        return 2
