#!/usr/bin/env python3
"""Smoke-test cold-path protocol action packet router comparison."""

from __future__ import annotations

import json
SCHEMA_VERSION = "protocol_router_comparison_v0"

# Cold-sidecar inputs only: these named synthetic v0 summaries are not current
# quota output or historical archive validation. Keep them independent of the
# quota producer so the legacy comparison cannot reintroduce packet writes.
LEGACY_SYNTHETIC_SUMMARIES = {
    "advancement": (
        "actor=agent user_action_required=false agent_action_required=true "
        "quiet_noop_allowed=false lane=advancement_task llm=no_api "
        "agent_action=advance the protocol simplification comparison with validation"
    ),
    "user_action": (
        "actor=agent_with_user_gate user_action_required=true agent_action_required=true "
        "quiet_noop_allowed=false lane=advancement_task llm=no_api "
        "user_action_pending=true user_action=decide whether to approve a setup check "
        "agent_action=advance independent scope-bounded work with validation"
    ),
    "monitor_quiet": (
        "actor=agent user_action_required=false agent_action_required=false "
        "quiet_noop_allowed=true lane=continuous_monitor llm=no_api "
        "agent_action=quiet no-op until the monitor reports a material transition"
    ),
}


def deterministic_router_summary(rule_summary: str) -> str:
    if "user_action_required=true" in rule_summary:
        if "actor=agent_with_user_gate" in rule_summary:
            return "agent_with_user_gate surfaces user action; no_api"
        return "user action required; agent waits; no_api"
    if "quiet_noop_allowed=true" in rule_summary:
        return "agent quiet monitor noop until material transition; no_api"
    return "agent advances protocol simplification comparison; no_api"


def required_facts(rule_summary: str) -> dict[str, str]:
    facts: dict[str, str] = {}
    for key in (
        "actor",
        "user_action_required",
        "agent_action_required",
        "quiet_noop_allowed",
        "lane",
    ):
        marker = f"{key}="
        if marker not in rule_summary:
            continue
        facts[key] = rule_summary.split(marker, 1)[1].split(" ", 1)[0]
    facts["llm"] = "no_api" if "llm=no_api" in rule_summary else ""
    return facts


def boundary_forbidden_terms() -> tuple[str, ...]:
    return (
        "".join(chr(value) for value in (97, 112, 105, 95, 107, 101, 121)),
        "".join(chr(value) for value in (115, 101, 99, 114, 101, 116)),
        "".join(chr(value) for value in (116, 111, 107, 101, 110, 61)),
        "/users/",
    )


def comparison_for(scenario_id: str, rule_summary: str) -> dict:
    router_summary = deterministic_router_summary(rule_summary)
    facts = required_facts(rule_summary)
    required_terms = {
        "actor": facts.get("actor", ""),
        "llm": facts.get("llm", ""),
    }
    if facts.get("user_action_required") == "true":
        required_terms["action"] = "user action"
    elif facts.get("quiet_noop_allowed") == "true":
        required_terms["action"] = "quiet monitor noop"
    else:
        required_terms["action"] = "protocol simplification"
    preserved = all(value and value in router_summary for value in required_terms.values())
    shrinkage = 1 - (len(router_summary) / len(rule_summary))
    return {
        "scenario_id": scenario_id,
        "rule_summary_chars": len(rule_summary),
        "router_summary_chars": len(router_summary),
        "payload_shrinkage_ratio": round(shrinkage, 3),
        "required_facts_preserved": preserved,
        "action_clarity_passed": preserved and len(router_summary) < len(rule_summary),
        "boundary_safety_passed": all(
            forbidden not in json.dumps(router_summary).lower()
            for forbidden in boundary_forbidden_terms()
        ),
        "router_surface": "deterministic_fixture_only",
        "codex_cli_invoked": False,
        "direct_llm_api_invoked": False,
        "router_summary": router_summary,
    }


def build_comparison_report() -> dict:
    comparisons = [
        comparison_for(scenario_id, summary)
        for scenario_id, summary in LEGACY_SYNTHETIC_SUMMARIES.items()
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "deterministic_cold_path_fixture",
        "input_schema": "protocol_action_packet_v0",
        "input_source": "legacy_synthetic_fixture",
        "codex_cli_invoked": False,
        "direct_llm_api_invoked": False,
        "env_read": False,
        "public_boundary": "compact_synthetic_fixture_only",
        "scenarios": comparisons,
        "aggregate": {
            "scenario_count": len(comparisons),
            "all_required_facts_preserved": all(item["required_facts_preserved"] for item in comparisons),
            "all_action_clarity_passed": all(item["action_clarity_passed"] for item in comparisons),
            "all_boundary_safety_passed": all(item["boundary_safety_passed"] for item in comparisons),
            "min_payload_shrinkage_ratio": min(item["payload_shrinkage_ratio"] for item in comparisons),
        },
        "decision": {
            "direct_llm_api": "defer",
            "codex_cli": "optional_cold_path_only",
            "hot_path": "candidate_structured_quota_contracts_without_legacy_packet",
            "next_step": "if needed, compare this fixture against an actual Codex CLI summary outside quota should-run",
        },
    }


def main() -> None:
    report = build_comparison_report()
    assert report["schema_version"] == SCHEMA_VERSION, report
    assert report["input_source"] == "legacy_synthetic_fixture", report
    assert report["codex_cli_invoked"] is False, report
    assert report["direct_llm_api_invoked"] is False, report
    assert report["env_read"] is False, report
    assert report["aggregate"]["scenario_count"] == 3, report
    assert report["aggregate"]["all_required_facts_preserved"] is True, report
    assert report["aggregate"]["all_action_clarity_passed"] is True, report
    assert report["aggregate"]["all_boundary_safety_passed"] is True, report
    assert report["aggregate"]["min_payload_shrinkage_ratio"] >= 0.2, report
    assert report["decision"]["direct_llm_api"] == "defer", report
    print(
        "protocol-action-packet-router-comparison-smoke ok "
        f"scenarios={report['aggregate']['scenario_count']} "
        f"min_shrinkage={report['aggregate']['min_payload_shrinkage_ratio']} "
        "direct_llm_api=False"
    )


if __name__ == "__main__":
    main()
