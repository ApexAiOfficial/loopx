"""The local primary guard never creates state or bypasses a durable hold."""

import json
import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from loopx.control_plane.coordination.coordination_state_contract_generated import (
    SHADOW_MANAGEMENT_STATE_SCHEMA,
)
from loopx.control_plane.coordination.shadow_management import (
    SHADOW_CAPTURE_PROFILE,
    ShadowManagementError,
    read_shadow_management_state,
    require_shadow_primary_write_allowed,
    shadow_management_state_path,
    shadow_maintenance_lock_target,
)


def test_absent_management_preserves_default_without_creating_files(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    assert require_shadow_primary_write_allowed(root, "goal-a") is None
    assert read_shadow_management_state(root, "goal-a") is None
    assert not root.exists()
    assert "authority-transition" in shadow_maintenance_lock_target(root, "goal-a").parts


@pytest.mark.parametrize("raw", ["{", "null", "[]", '{"status":"active"}'])
def test_corrupt_management_holds_before_any_primary_write(tmp_path: Path, raw: str) -> None:
    path = shadow_management_state_path(tmp_path, "goal-a")
    path.parent.mkdir(parents=True)
    path.write_text(raw)
    before = path.read_bytes()
    with pytest.raises(ShadowManagementError) as failure:
        require_shadow_primary_write_allowed(tmp_path, "goal-a")
    assert failure.value.code == "shadow_management_state_invalid"
    assert path.read_bytes() == before


def test_python_reads_typescript_binding_across_root_alias_and_rejects_cross_root_replay(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    alias = tmp_path / "runtime-alias"
    try:
        alias.symlink_to(root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    script = """
import {bootstrapManagedShadow} from './loopx/control_plane/coordination/shadow_management.ts';
const root = process.argv[1];
const request = {runtime_root:root,goal_id:'goal-a',operation_id:'bootstrap:guard',source_version:'v1',source_snapshot:{},projection:{goal_id:'goal-a',todos:[],leases:[]}};
const result = await bootstrapManagedShadow(request,{withPrimaryLocks:async fn=>await fn(),verifySourceSnapshot:async()=>{}});
process.stdout.write(JSON.stringify(result));
"""
    result = subprocess.run(
        ["node", "--no-warnings", "--experimental-strip-types", "--input-type=module", "-e", script, str(alias)],
        check=True, capture_output=True, text=True,
    )
    applied = json.loads(result.stdout)
    assert applied["status"] == "applied"
    binding = require_shadow_primary_write_allowed(alias, "goal-a")
    assert binding is not None
    assert binding["capture_lineage_id"] == applied["capture_lineage_id"]
    assert require_shadow_primary_write_allowed(root, "goal-a") == binding
    state_path = shadow_management_state_path(root, "goal-a")
    state = json.loads(state_path.read_text())
    lexical_digest = "sha256:" + hashlib.sha256(str(alias).encode()).hexdigest()
    assert lexical_digest != binding["source_root_digest"]
    state["source_root_digest"] = lexical_digest
    state_path.write_text(json.dumps(state))
    with pytest.raises(ShadowManagementError, match="shadow_management_state_invalid"):
        require_shadow_primary_write_allowed(alias, "goal-a")
    state["source_root_digest"] = binding["source_root_digest"]
    state_path.write_text(json.dumps(state))
    other = tmp_path / "other-root"
    destination = shadow_management_state_path(other, "goal-a")
    destination.parent.mkdir(parents=True)
    destination.write_bytes(state_path.read_bytes())
    with pytest.raises(ShadowManagementError, match="shadow_management_state_invalid"):
        require_shadow_primary_write_allowed(other, "goal-a")


@pytest.mark.parametrize("status", ["bootstrapping", "rolling_back"])
def test_pending_journal_is_a_primary_hold(tmp_path: Path, status: str) -> None:
    root_digest = "sha256:" + hashlib.sha256(str(tmp_path).encode()).hexdigest()
    state = {
        "schema_version": "loopx_shadow_management_state_v1", "goal_id": "goal-a",
        "source_root_digest": root_digest, "status": status, "binding": None,
        "operation": {"kind": "bootstrap" if status == "bootstrapping" else "rollback",
                      "operation_id": "operation:pending", "request_digest": "sha256:" + "1" * 64,
                      "manifest_digest": "sha256:" + "2" * 64, "phase": "prepared"},
        "previous_operation_id": None, "result": None,
    }
    path = shadow_management_state_path(tmp_path, "goal-a")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(state))
    with pytest.raises(ShadowManagementError) as failure:
        require_shadow_primary_write_allowed(tmp_path, "goal-a")
    assert failure.value.code == "shadow_management_in_progress"


@pytest.mark.stage2c_e2e
def test_bound_source_path_comes_from_the_verified_typescript_bootstrap(tmp_path: Path) -> None:
    from loopx.control_plane.coordination import shadow_management as management
    from shadow_e2e_fixture import workspace

    w = workspace(tmp_path)
    binding = require_shadow_primary_write_allowed(w.runtime, w.goal)
    assert binding is not None
    before = {str(path.relative_to(w.runtime)): path.read_bytes() for path in w.runtime.rglob("*") if path.is_file()}
    assert management.read_shadow_bootstrap_source_path(w.runtime, w.goal, binding) == w.state
    with pytest.raises(ShadowManagementError, match="stale_generation"):
        management.read_shadow_bootstrap_source_path(w.runtime, w.goal, {**binding, "capture_lineage_id": "another-lineage"})
    assert {str(path.relative_to(w.runtime)): path.read_bytes() for path in w.runtime.rglob("*") if path.is_file()} == before


@pytest.mark.stage2c_e2e
@pytest.mark.parametrize("damage", ["altered", "missing"])
def test_bound_source_path_never_accepts_or_repairs_a_damaged_manifest(tmp_path: Path, damage: str) -> None:
    from loopx.control_plane.coordination import shadow_management as management
    from shadow_e2e_fixture import workspace

    w = workspace(tmp_path)
    binding = require_shadow_primary_write_allowed(w.runtime, w.goal)
    assert binding is not None
    [manifest] = management.shadow_management_directory(w.runtime, w.goal).glob("operations/*/manifest.json")
    if damage == "altered":
        value = json.loads(manifest.read_bytes())
        value["request"]["source_snapshot"]["state_path"] = str(tmp_path / "foreign-state.md")
        manifest.write_text(json.dumps(value))
    else:
        manifest.unlink()
    before = {str(path.relative_to(w.runtime)): path.read_bytes() for path in w.runtime.rglob("*") if path.is_file()}
    with pytest.raises(ShadowManagementError, match="shadow_management_manifest_invalid"):
        management.read_shadow_bootstrap_source_path(w.runtime, w.goal, binding)
    assert {str(path.relative_to(w.runtime)): path.read_bytes() for path in w.runtime.rglob("*") if path.is_file()} == before


def _root_digest(path: Path, *, canonical: bool) -> str:
    spelling = os.path.realpath(path) if canonical else os.path.abspath(path)
    return "sha256:" + hashlib.sha256(spelling.encode("utf-8")).hexdigest()


def _active_journal(*, state_digest: str, binding_digest: str) -> dict:
    """An active journal in the shape the TypeScript owner writes, with separately chosen root digests."""

    return {
        "schema_version": SHADOW_MANAGEMENT_STATE_SCHEMA,
        "goal_id": "goal-a",
        "source_root_digest": state_digest,
        "status": "active",
        "binding": {
            "capture_profile": SHADOW_CAPTURE_PROFILE,
            "capture_lineage_id": "lineage-a",
            "source_root_digest": binding_digest,
            "store_identity": "file:" + "a" * 32,
            "bootstrap_operation_id": "bootstrap:guard",
            "bootstrap_provider_revision": "file:1:" + "b" * 24,
        },
        "operation": {
            "kind": "bootstrap",
            "operation_id": "bootstrap:guard",
            "request_digest": "sha256:" + "c" * 64,
            "manifest_digest": "sha256:" + "d" * 64,
            "phase": "complete",
        },
        "previous_operation_id": None,
        "result": {},
    }


_TYPESCRIPT_READ = """
import {readShadowManagementState} from './loopx/control_plane/coordination/shadow_management.ts';
try {
  const state = await readShadowManagementState(process.argv[1], 'goal-a');
  process.stdout.write(JSON.stringify({accepted: state !== null}));
} catch (error) {
  process.stdout.write(JSON.stringify({accepted: false, code: error?.code ?? error?.reason_code ?? String(error)}));
}
"""


def _typescript_reads(root: Path) -> dict:
    result = subprocess.run(
        ["node", "--no-warnings", "--experimental-strip-types", "--input-type=module", "-e", _TYPESCRIPT_READ, str(root)],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    ("state_canonical", "binding_canonical"),
    [(False, True), (True, False)],
    ids=["lexical-journal-canonical-binding", "canonical-journal-lexical-binding"],
)
def test_mixed_root_digests_are_rejected_by_both_readers_without_touching_the_journal(
    tmp_path: Path, state_canonical: bool, binding_canonical: bool,
) -> None:
    """Either spelling may identify the root, but journal and binding must agree exactly.

    The TypeScript decoder requires `binding.source_root_digest === state.source_root_digest`;
    the Python guard must hold the same line, or a journal Python keeps writing under is one
    TypeScript refuses to read back after a restart (#4892 review).
    """

    real = tmp_path / "runtime"
    real.mkdir()
    alias = tmp_path / "runtime-alias"
    try:
        alias.symlink_to(real, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    assert _root_digest(alias, canonical=True) != _root_digest(alias, canonical=False)
    path = shadow_management_state_path(alias, "goal-a")
    path.parent.mkdir(parents=True)

    # Positive control: an agreeing journal is accepted by both readers, so the
    # rejections below are about the mixture, not about the fixture.
    agreeing = _root_digest(alias, canonical=True)
    path.write_text(json.dumps(_active_journal(state_digest=agreeing, binding_digest=agreeing)))
    assert require_shadow_primary_write_allowed(alias, "goal-a") is not None
    assert _typescript_reads(alias) == {"accepted": True}

    mixed = _active_journal(
        state_digest=_root_digest(alias, canonical=state_canonical),
        binding_digest=_root_digest(alias, canonical=binding_canonical),
    )
    path.write_text(json.dumps(mixed))
    before = path.read_bytes()
    with pytest.raises(ShadowManagementError) as failure:
        require_shadow_primary_write_allowed(alias, "goal-a")
    assert failure.value.code == "shadow_management_state_invalid"
    assert path.read_bytes() == before
    assert _typescript_reads(alias) == {"accepted": False, "code": "shadow_management_state_invalid"}
    assert path.read_bytes() == before
