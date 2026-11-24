from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.cli import main
from loopx.configure_goal import configure_goal


GOAL_ID = "local-authority-shadow-config"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _registry(tmp_path: Path) -> Path:
    state = tmp_path / "ACTIVE_GOAL_STATE.md"
    state.write_text(
        "---\n"
        f"goal_id: {GOAL_ID}\n"
        "handoff_mode: hard_lease\n"
        "---\n\n"
        "## Agent Todo\n\n",
        encoding="utf-8",
    )
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": GOAL_ID,
                        "repo": str(tmp_path),
                        "state_file": state.name,
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": ["agent-a", "agent-b"],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return registry


@pytest.mark.parametrize("execute", [False, True])
def test_retired_enable_rejects_without_rewriting_registry(tmp_path: Path, execute: bool) -> None:
    registry = _registry(tmp_path)
    before = registry.read_bytes()
    with pytest.raises(ValueError, match="local_authority_shadow_retired"):
        configure_goal(registry_path=registry, goal_id=GOAL_ID,
                       local_authority_shadow_file=True, execute=execute)
    assert registry.read_bytes() == before


def test_clear_retired_setting_preserves_runtime_config_and_peer_registration(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    data = json.loads(registry.read_text())
    data["goals"][0]["coordination"]["authority_shadow"] = {
        "schema_version": "loopx_local_authority_shadow_config_v0", "mode": "file_one_way"}
    registry.write_text(json.dumps(data))
    result = configure_goal(registry_path=registry, goal_id=GOAL_ID,
        clear_local_authority_shadow=True, coordination_runtime_shadow_file=True, execute=True)
    assert result["before"]["local_authority_shadow"]["status"] == "retired"
    assert result["before"]["local_authority_shadow"]["enabled"] is False
    assert result["after"]["local_authority_shadow"]["status"] == "disabled"
    goal = json.loads(registry.read_text())["goals"][0]
    assert "authority_shadow" not in goal["coordination"]
    assert goal["coordination"]["runtime_shadow"]["enabled"] is True
    assert goal["coordination"]["registered_agents"] == ["agent-a", "agent-b"]


def test_configure_goal_rejects_enable_and_clear_in_one_operation(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    with pytest.raises(ValueError, match="cannot be combined"):
        configure_goal(
            registry_path=registry,
            goal_id=GOAL_ID,
            local_authority_shadow_file=True,
            clear_local_authority_shadow=True,
        )


def test_configure_goal_exposes_transaction_bound_runtime_shadow_separately(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)

    preview = configure_goal(
        registry_path=registry,
        goal_id=GOAL_ID,
        coordination_runtime_shadow_file=True,
        execute=False,
    )
    assert preview["changed_fields"] == ["coordination_runtime_shadow"]
    assert preview["before"]["coordination_runtime_shadow"] == {
        "enabled": False,
        "provider": None,
        "status": "configuration_absent",
    }
    assert preview["after"]["coordination_runtime_shadow"] == {
        "enabled": True,
        "provider": "file_v0",
        "status": "enabled",
    }
    assert preview["after"]["local_authority_shadow"]["enabled"] is False

    applied = configure_goal(
        registry_path=registry,
        goal_id=GOAL_ID,
        coordination_runtime_shadow_file=True,
        execute=True,
    )
    assert applied["written"] is True
    goal = json.loads(registry.read_text(encoding="utf-8"))["goals"][0]
    assert goal["coordination"]["runtime_shadow"] == {
        "enabled": True,
        "schema_version": "loopx_coordination_runtime_shadow_config_v0",
        "provider": "file_v0",
    }
    assert "authority_shadow" not in goal["coordination"]

    feature = next(
        item
        for item in applied["configuration_catalog"]["features"]
        if item["feature_id"] == "coordination_runtime_shadow"
    )
    assert feature["current"]["enabled"] is True
    assert feature["commands"]["apply_enable"].endswith(
        "--coordination-runtime-shadow-file --execute"
    )

    cleared = configure_goal(
        registry_path=registry,
        goal_id=GOAL_ID,
        clear_coordination_runtime_shadow=True,
        execute=True,
    )
    assert cleared["changed_fields"] == ["coordination_runtime_shadow"]
    goal = json.loads(registry.read_text(encoding="utf-8"))["goals"][0]
    assert "runtime_shadow" not in goal["coordination"]


def test_cli_rejects_retired_activation_and_exposes_no_enable_action(tmp_path: Path, capsys) -> None:
    registry = _registry(tmp_path)
    before = registry.read_bytes()
    code = main(["--registry", str(registry), "--format", "json", "configure-goal",
                 "--goal-id", GOAL_ID, "--local-authority-shadow-file"])
    assert code != 0
    assert "local_authority_shadow_retired" in capsys.readouterr().out
    assert registry.read_bytes() == before
    result = configure_goal(registry_path=registry, goal_id=GOAL_ID)
    feature = next(row for row in result["configuration_catalog"]["features"]
                   if row["feature_id"] == "local_authority_shadow")
    assert feature["availability"] == "retired"
    assert "apply_enable" not in feature["commands"]
    assert "--clear-local-authority-shadow" in feature["commands"]["apply_disable"]
    from loopx.capabilities.configuration_ui import capability_configuration_editor
    assert capability_configuration_editor("local_authority_shadow")["writable_scopes"] == []


@pytest.mark.parametrize("raw", [None, {}, {"mode": "other"}])
def test_malformed_retained_config_can_be_cleared_without_activation(tmp_path: Path, raw) -> None:
    registry = _registry(tmp_path)
    data = json.loads(registry.read_text())
    data["goals"][0]["coordination"]["authority_shadow"] = raw
    registry.write_text(json.dumps(data))
    result = configure_goal(registry_path=registry, goal_id=GOAL_ID, clear_local_authority_shadow=True, execute=True)
    assert result["before"]["local_authority_shadow"]["status"] == "invalid"
    assert result["after"]["local_authority_shadow"]["status"] == "disabled"
