from __future__ import annotations

import json
import re

from ..goals.active_state_metadata import (
    markdown_blockquote,
    markdown_frontmatter_string,
    split_state_frontmatter,
)


def render_registration_state(
    *,
    project_id: str,
    goal_id: str,
    objective: str,
    non_goals: list[str],
    acceptance: list[str],
    unknowns: list[str],
    next_effect: str,
    stop_condition: str,
    updated_at: str,
) -> str:
    def bullets(items: list[str], *, empty: str) -> str:
        return "\n".join(f"- {item}" for item in items) if items else f"- {empty}"

    return f"""---
status: active
owner_mode: goal
project_id: {json.dumps(project_id, ensure_ascii=False)}
objective: {markdown_frontmatter_string(objective)}
updated_at: {updated_at}
adapter_id: {goal_id}
---

# Active Goal State

## Objective

{markdown_blockquote(objective)}

## Acceptance

{bullets(acceptance, empty="No acceptance evidence recorded.")}

## Non-Goals

{bullets(non_goals, empty="No additional non-goals recorded.")}

## Unknowns

{bullets(unknowns, empty="No decision-relevant unknowns recorded.")}

## User Todo / Owner Review Reading Queue

## Agent Todo

## Next Action

- {next_effect}

## Stop Condition

- {stop_condition}

## Progress Ledger

- Registered Project `{project_id}` and Goal `{goal_id}`.
"""


def registration_state_matches(
    existing: str,
    expected: str,
    *,
    objective: str,
) -> bool:
    """Compare metadata values and exact narrative without rewriting old state."""

    existing_metadata, existing_body = split_state_frontmatter(existing)
    expected_metadata, expected_body = split_state_frontmatter(expected)
    if existing_metadata != expected_metadata:
        return False
    marker = "\n## Objective\n\n"
    existing_prefix, separator, existing_section = existing_body.partition(marker)
    expected_prefix, _, expected_section = expected_body.partition(marker)
    if not separator or existing_prefix != expected_prefix:
        return False
    quoted = markdown_blockquote(objective)
    remainder = expected_section[len(quoted) :]
    return existing_section in (quoted + remainder, objective + remainder)


def registration_state_updated_at(state_text: str) -> str | None:
    match = re.search(r"^updated_at: (.+)$", state_text, flags=re.MULTILINE)
    return match.group(1) if match is not None else None
