"""`loopx-jev sentinel compare`: the in-repository differential harness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_MODEL = "jev-1.13.0"


def register(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser(
        "sentinel",
        help="compare the typed repeat fuse with external review on a frozen matrix",
    )
    operations = parser.add_subparsers(dest="sentinel_command", required=True)
    compare = operations.add_parser(
        "compare", help="replay recorded answers, or record them with --live"
    )
    compare.add_argument("--matrix", type=Path, required=True)
    compare.add_argument("--responses", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    compare.add_argument("--live", action="store_true", help="call the provider and record")
    compare.add_argument("--model", default=DEFAULT_MODEL)
    compare.add_argument("--deadline-ms", type=int, default=5000)
    compare.add_argument("--drift-threshold", type=int, default=2)


def run(parsed: argparse.Namespace) -> int:
    from .sentinel_compare import compare, write_comparison
    from .sentinel_matrix import load_sentinel_matrix

    if not 100 <= parsed.deadline_ms <= 30000 or not 2 <= parsed.drift_threshold <= 20:
        raise ValueError("invalid_sentinel_budget")
    matrix = load_sentinel_matrix(parsed.matrix)
    comparison = compare(
        matrix,
        responses=parsed.responses,
        live=bool(parsed.live),
        model=parsed.model,
        deadline_ms=parsed.deadline_ms,
        drift_threshold=parsed.drift_threshold,
    )
    write_comparison(parsed.output, comparison)
    print(
        json.dumps(
            {
                "status": "compared",
                "execution": comparison["execution"],
                "output": str(parsed.output),
                "aggregate": comparison["aggregate"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0
