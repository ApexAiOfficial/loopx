"""One rule for which commands a blocked packet may spell out, shared by tests and smokes.

A packet that withholds a continuation is only as safe as every surface that
carries it: the top-level command map, nested registration and activation
gates, the slash-command catalog, and the Markdown a host reads. This module
states the rule once so a unit test and a shipped CLI smoke cannot drift apart
on what counts as a runnable verb.
"""

from __future__ import annotations

import re
from typing import Any, Iterator

COMMAND_FAMILY = re.compile(r"loopx\s+([a-z][a-z-]*)")

# Every command family that can move Goal state, a lane, a lease, quota or a host
# loop. Read-only inspection stays out: `status`, `doctor`,
# `bootstrap-command-pack`, and a `backup-state` preview without `--execute`.
MUTATION_COMMAND_FAMILIES = frozenset(
    {
        "agent-onboard",
        "bind-agent-thread",
        "bootstrap",
        "configure-goal",
        "connect",
        "heartbeat-prompt",
        "issue-fix",
        "quota",
        "refresh-state",
        "register-agent",
        "start-goal",
        "task-lease",
        "todo",
    }
)


def _strings(value: Any, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _strings(item, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value


def continuation_verb_findings(payload: Any) -> list[tuple[str, str]]:
    """Every line in ``payload`` that spells a runnable mutation or ``--execute``.

    Judged per line: a runnable command always carries its own ``--execute`` on
    the same line, while prose that only explains a preview boundary mentions the
    two apart.
    """

    return [
        (path, line[:120])
        for path, text in _strings(payload, "packet")
        for line in text.splitlines()
        if "loopx " in line
        and (
            "--execute" in line
            or any(
                family in MUTATION_COMMAND_FAMILIES
                for family in COMMAND_FAMILY.findall(line)
            )
        )
    ]


def assert_no_continuation_verb(payload: Any, *, source: str = "packet") -> None:
    """Fail on any command this packet's surfaces still offer for mutation."""

    findings = continuation_verb_findings(payload)
    assert findings == [], (source, findings)
