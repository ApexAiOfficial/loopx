from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import threading

import pytest

from loopx.authority import register_authority_source
from loopx.configure_goal import configure_goal
from loopx.control_plane.goals import deletion_service
from loopx.control_plane.goals.activation_service import set_goal_activation_state
from loopx.control_plane.goals.deletion_service import delete_stopped_goal
from loopx.control_plane.projects.registry import bind_session
from loopx.control_plane.quota.goal_boundary import registry_goal_by_id
from loopx.global_registry import sync_project_registry_to_global
from loopx.goal_mode_context import resolve_goal_context
from loopx.history import load_registry


def _payload_digest(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _strict_envelope(payload: dict[str, object]) -> list[object]:
    return [
        {
            "schema_version": "loopx_project_registry_envelope_v1",
            "minimum_writer_protocol": "goal_instance_v1",
            "payload_sha256": _payload_digest(payload),
        },
        payload,
    ]


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_load_registry_accepts_valid_strict_project_envelope(tmp_path: Path) -> None:
    registry_path = tmp_path / ".loopx" / "registry.json"
    payload: dict[str, object] = {"schema_version": "0.1", "goals": []}
    _write_json(registry_path, _strict_envelope(payload))

    assert load_registry(registry_path) == payload


def test_bind_session_preserves_strict_project_envelope(tmp_path: Path) -> None:
    registry_path = tmp_path / ".loopx" / "registry.json"
    payload: dict[str, object] = {
        "schema_version": "0.1",
        "projects": [
            {
                "project_id": "atlas",
                "project_kind": "work",
                "knowledge_root": str(tmp_path / "atlas"),
                "repository_bindings": [],
                "external_locator_bindings": [],
            }
        ],
        "goals": [
            {
                "id": "atlas-import",
                "project_id": "atlas",
                "status": "active",
            }
        ],
    }
    _write_json(registry_path, _strict_envelope(payload))

    result = bind_session(
        registry_path=registry_path,
        session_id="session-public-fixture",
        goal_id="atlas-import",
    )

    root = json.loads(registry_path.read_text(encoding="utf-8"))
    assert result["changed"] is True
    assert isinstance(root, list)
    assert len(root) == 2
    assert root[0]["schema_version"] == "loopx_project_registry_envelope_v1"
    assert root[0]["payload_sha256"] == _payload_digest(root[1])
    assert root[1]["session_bindings"] == [
        {
            "session_id": "session-public-fixture",
            "foreground_goal_id": "atlas-import",
        }
    ]


def test_shared_project_readers_accept_strict_project_envelope(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    registry_path = project / ".loopx" / "registry.json"
    payload: dict[str, object] = {
        "schema_version": "0.1",
        "goals": [
            {
                "id": "goal-one",
                "repo": str(project),
                "coordination": {"registered_agents": ["agent-one"]},
            }
        ],
    }
    _write_json(registry_path, _strict_envelope(payload))

    context = resolve_goal_context(
        project,
        preferred_goal_id="goal-one",
        preferred_agent_id="agent-one",
        require_preferred_binding=True,
    )
    indexed = registry_goal_by_id({"registry": str(registry_path)})

    assert context is not None
    assert context["goal_id"] == "goal-one"
    assert indexed["goal-one"]["repo"] == str(project)


def test_configure_goal_preserves_strict_project_envelope(tmp_path: Path) -> None:
    registry_path = tmp_path / ".loopx" / "registry.json"
    payload: dict[str, object] = {
        "schema_version": "0.1",
        "goals": [{"id": "goal-one", "status": "active"}],
    }
    _write_json(registry_path, _strict_envelope(payload))

    result = configure_goal(
        registry_path=registry_path,
        goal_id="goal-one",
        quota_compute=2.0,
        execute=True,
    )

    root = json.loads(registry_path.read_text(encoding="utf-8"))
    assert result["written"] is True
    assert root[0]["payload_sha256"] == _payload_digest(root[1])
    assert root[1]["goals"][0]["quota"]["compute"] == 2.0


def test_activation_and_deletion_preserve_strict_project_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    runtime_root = tmp_path / "runtime"
    registry_path = project / ".loopx" / "registry.json"
    payload: dict[str, object] = {
        "schema_version": "0.1",
        "common_runtime_root": str(runtime_root),
        "goals": [{"id": "goal-one", "repo": str(project)}],
    }
    _write_json(registry_path, _strict_envelope(payload))
    sync_project_registry_to_global(
        registry_path=registry_path,
        runtime_root_override=str(runtime_root),
        goal_id="goal-one",
        dry_run=False,
    )

    stopped = set_goal_activation_state(
        registry_path=runtime_root / "registry.global.json",
        goal_id="goal-one",
        state="stopped",
        actor_kind="owner",
        execute=True,
    )
    preview = delete_stopped_goal(
        registry_path=runtime_root / "registry.global.json",
        goal_id="goal-one",
        execute=False,
    )
    original_write = deletion_service._write_locked_registry
    write_count = 0

    def interrupt_after_source_commit(**kwargs: object) -> None:
        nonlocal write_count
        original_write(**kwargs)
        write_count += 1
        if write_count == 1:
            raise KeyboardInterrupt("simulated process termination")

    monkeypatch.setattr(
        deletion_service,
        "_write_locked_registry",
        interrupt_after_source_commit,
    )
    with pytest.raises(KeyboardInterrupt, match="simulated process termination"):
        delete_stopped_goal(
            registry_path=runtime_root / "registry.global.json",
            goal_id="goal-one",
            execute=True,
            expected_state_fingerprint=preview["observed_state_fingerprint"],
            expected_source_basis=preview["source_basis"],
        )
    monkeypatch.setattr(
        deletion_service,
        "_write_locked_registry",
        original_write,
    )
    deleted = delete_stopped_goal(
        registry_path=registry_path,
        goal_id="goal-one",
        execute=True,
        expected_state_fingerprint=preview["observed_state_fingerprint"],
        expected_source_basis=preview["source_basis"],
    )

    source_root = json.loads(registry_path.read_text(encoding="utf-8"))
    global_root = json.loads(
        (runtime_root / "registry.global.json").read_text(encoding="utf-8")
    )
    assert stopped["readback"]["verified"] is True
    assert deleted["recovered"] is True
    assert deleted["readback"]["verified"] is True
    assert source_root[0]["payload_sha256"] == _payload_digest(source_root[1])
    assert source_root[1]["goals"] == []
    assert isinstance(global_root, dict)
    assert global_root["goals"] == []


def test_register_authority_source_preserves_concurrent_peer_update(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / ".loopx" / "registry.json"
    _write_json(
        registry_path,
        {
            "schema_version": "0.1",
            "goals": [
                {
                    "id": "goal-one",
                    "repo": str(tmp_path),
                    "authority_registry": {},
                }
            ],
        },
    )
    ready = threading.Barrier(2)

    def register(source_id: str) -> dict[str, object]:
        ready.wait(timeout=5)
        return register_authority_source(
            registry_path=registry_path,
            goal_id="goal-one",
            source_id=source_id,
            source_ref=None,
            source_kind="repository",
            role="reference",
            freshness="current",
            owner_status=None,
            gate_status=None,
            boundary="public",
            revision=None,
            conflict_rule=None,
            topic=None,
            dry_run=False,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(register, ("source-a", "source-b")))

    materials = (
        load_registry(registry_path)["goals"][0]["authority_registry"][
            "project_materials"
        ]
    )
    assert all(result["written"] is True for result in results)
    assert set(materials) == {"source-a", "source-b"}


def test_delete_stopped_goal_compensates_in_reverse_write_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "runtime"
    source_registry = tmp_path / "project" / ".loopx" / "registry.json"
    _write_json(
        source_registry,
        {
            "schema_version": "0.1",
            "common_runtime_root": str(runtime_root),
            "goals": [
                {
                    "id": "goal-one",
                    "repo": str(tmp_path / "project"),
                }
            ],
        },
    )
    synced = sync_project_registry_to_global(
        registry_path=source_registry,
        runtime_root_override=str(runtime_root),
        goal_id="goal-one",
        dry_run=False,
    )
    assert synced["ok"] is True
    global_registry = runtime_root / "registry.global.json"
    stopped = set_goal_activation_state(
        registry_path=global_registry,
        goal_id="goal-one",
        state="stopped",
        actor_kind="owner",
        execute=True,
    )
    assert stopped["ok"] is True

    real_write = deletion_service._write_locked_registry
    real_restore = deletion_service._restore_locked_registry
    real_load = deletion_service.load_registry
    writes: list[Path] = []
    deletion_writes = 0
    fail_readback = False

    def tracked_write(**kwargs: object) -> None:
        nonlocal deletion_writes, fail_readback
        path = kwargs["path"]
        assert isinstance(path, Path)
        writes.append(path)
        real_write(**kwargs)
        deletion_writes += 1
        if deletion_writes == 2:
            fail_readback = True

    def tracked_restore(**kwargs: object) -> None:
        path = kwargs["path"]
        assert isinstance(path, Path)
        writes.append(path)
        real_restore(**kwargs)

    def fail_first_readback(path: Path) -> dict[str, object]:
        nonlocal fail_readback
        if fail_readback:
            fail_readback = False
            raise OSError("injected readback failure")
        return real_load(path)

    monkeypatch.setattr(deletion_service, "_write_locked_registry", tracked_write)
    monkeypatch.setattr(deletion_service, "_restore_locked_registry", tracked_restore)
    monkeypatch.setattr(deletion_service, "load_registry", fail_first_readback)

    with pytest.raises(OSError, match="injected readback failure"):
        delete_stopped_goal(
            registry_path=global_registry,
            goal_id="goal-one",
            execute=True,
        )

    assert writes[2:] == list(reversed(writes[:2]))
