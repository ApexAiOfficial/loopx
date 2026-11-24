"""Real canonical projection delivery under overlapping commits and retry."""

import json
import subprocess
from pathlib import Path

import pytest
from canonical_authority_fixture import (
    initialize_canonical_authority,
    isolate_sqlite_runtime,
)
from loopx.control_plane.coordination.runtime_shadow import (
    build_todo_runtime_shadow_projection,
)
from loopx.control_plane.todos import provider_projection

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(params=["file", "sqlite"])
def canonical_projection(tmp_path, monkeypatch, request):
    isolate_sqlite_runtime(tmp_path, monkeypatch)
    runtime, state, registry = (
        tmp_path / "runtime",
        tmp_path / "state.md",
        tmp_path / "registry.json",
    )
    state.write_text("# Recovery\n\nHuman narrative.\n\n## Agent Todo\n")
    registry.write_text(
        json.dumps(
            {
                "common_runtime_root": str(runtime),
                "goals": [
                    {
                        "id": "projection-goal",
                        "repo": str(tmp_path),
                        "state_file": state.name,
                    }
                ],
            }
        )
    )
    projection = build_todo_runtime_shadow_projection(
        goal_id="projection-goal",
        todos=[
            {
                "schema_version": "todo_item_v0",
                "todo_id": "todo_work",
                "role": "agent",
                "status": "open",
                "done": False,
                "text": "Canonical work",
                "archive_state": "active",
                "source_section": "Agent Todo",
                "index": 1,
                "task_class": "advancement_task",
            }
        ],
        leases=[],
        handoff_mode="soft_claim",
    )
    first = initialize_canonical_authority(
        runtime, "projection-goal", projection, state_path=state, provider=request.param
    )
    args = {
        "registry_path": registry,
        "runtime_root": runtime,
        "goal_id": "projection-goal",
    }

    def advance():
        # A real concurrent authority commit; the display lock is not its CAS.
        script = """import {openLocalAuthorityStore} from './loopx/control_plane/coordination/local_authority_provider.ts';
const store=await openLocalAuthorityStore(process.argv[1],'projection-goal');
const h=await store.loadAuthority();
const r=await store.commitAuthority({expected_provider_revision:h.provider_revision,
 operation_id:'overlap-'+h.cursor,next_projection:h.head,events:[],receipts:[]});
if(r.status!=='applied')throw new Error(JSON.stringify(r));console.log(JSON.stringify(r));"""
        child = subprocess.run(
            [
                "node",
                "--no-warnings",
                "--experimental-strip-types",
                "--input-type=module",
                "-e",
                script,
                str(runtime),
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=45,
            check=True,
        )
        return json.loads(child.stdout)

    return args, state, first, advance


def test_delivery_catches_up_after_real_overlapping_commit(
    canonical_projection, monkeypatch
):
    args, state, first, advance = canonical_projection
    write = provider_projection.atomic_write_state_text
    commits = []

    def overlap(*a, **kw):
        write(*a, **kw)
        if not commits:
            commits.append(advance())

    monkeypatch.setattr(provider_projection, "atomic_write_state_text", overlap)
    result = provider_projection.project_current_canonical_todos(**args)
    assert result["provider_revision"] == commits[0]["provider_revision"]
    assert result["status"] == "delivered"
    assert result["delivery_attempts"] == 2
    assert "Human narrative." in state.read_text()
    assert commits[0]["provider_revision"] in state.read_text()
    assert first["provider_revision"] not in state.read_text()


def test_pinned_projection_reports_overlap_without_retargeting(
    canonical_projection, monkeypatch
):
    args, state, first, advance = canonical_projection
    write = provider_projection.atomic_write_state_text
    commits = []

    def overlap(*a, **kw):
        write(*a, **kw)
        commits.append(advance())

    monkeypatch.setattr(provider_projection, "atomic_write_state_text", overlap)
    result = provider_projection.project_current_canonical_todos(
        **args, expected_provider_revision=first["provider_revision"]
    )
    assert result["status"] == "pending"
    assert result["provider_revision"] == first["provider_revision"]
    assert result["observed_provider_revision"] == commits[0]["provider_revision"]
    assert result["retry_business_mutation"] is False
    assert result["delivery_attempts"] == 1
    assert first["provider_revision"] in state.read_text()


def test_continuous_commits_stay_pending_and_recover_without_business_replay(
    canonical_projection, monkeypatch
):
    args, state, _, advance = canonical_projection
    write = provider_projection.atomic_write_state_text
    commits = []

    def overlap(*a, **kw):
        write(*a, **kw)
        commits.append(advance())

    with monkeypatch.context() as patch:
        patch.setattr(provider_projection, "atomic_write_state_text", overlap)
        committed = provider_projection.settle_canonical_todo_projection(
            {
                "status": "applied",
                "changed": True,
                "operation_id": "original-business-operation",
            },
            **args,
        )
    assert committed["status"] == "applied"
    assert committed["projection_delivery"] == "pending"
    assert committed["projection_outbox"]["delivery_attempts"] == 3
    assert committed["projection_outbox"]["retry_business_mutation"] is False
    assert len(commits) == 3
    replay = provider_projection.settle_canonical_todo_projection(
        {
            "status": "replayed",
            "changed": False,
            "operation_id": "original-business-operation",
        },
        **args,
    )
    assert replay["projection_delivery"] == "delivered"
    assert (
        replay["projection_outbox"]["provider_revision"]
        == commits[-1]["provider_revision"]
    )
    assert len(commits) == 3
    assert "Human narrative." in state.read_text()


def test_missing_display_can_catch_up_without_create_only_collision(
    canonical_projection, monkeypatch
):
    args, state, _, advance = canonical_projection
    state.unlink()
    write = provider_projection.atomic_write_state_text
    commits = []

    def overlap(*a, **kw):
        write(*a, **kw)
        if not commits:
            commits.append(advance())

    monkeypatch.setattr(provider_projection, "atomic_write_state_text", overlap)
    result = provider_projection.project_current_canonical_todos(**args)
    assert result["status"] == "delivered" and result["delivery_attempts"] == 2
    assert result["recovery_scope"] == "todo_sections_only"
    assert result["narrative_preserved"] is False
    assert commits[-1]["provider_revision"] in state.read_text()


def test_confirmation_outage_preserves_committed_business_and_retries(
    canonical_projection, monkeypatch
):
    args, state, _, _ = canonical_projection
    read = provider_projection.read_canonical_todos_if_promoted

    def fail_confirmation(**kwargs):
        if kwargs.get("projection_readback") is not None:
            raise provider_projection.LocalCoordinationAuthorityUnavailable(
                "synthetic read outage", code="unavailable", payload={}
            )
        return read(**kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(
            provider_projection, "read_canonical_todos_if_promoted", fail_confirmation
        )
        result = provider_projection.settle_canonical_todo_projection(
            {"status": "applied", "changed": True}, **args
        )
    assert result["status"] == "applied" and result["projection_delivery"] == "pending"
    assert result["projection_outbox"]["retry_business_mutation"] is False
    assert "Canonical work" in state.read_text()
    replay = provider_projection.settle_canonical_todo_projection(
        {"status": "replayed", "changed": False}, **args
    )
    assert replay["projection_delivery"] == "current"


def test_downlevel_runtime_cannot_acknowledge_delivery(
    canonical_projection, monkeypatch
):
    from loopx.control_plane.coordination import local_authority

    args, state, first, _ = canonical_projection
    invoke = local_authority.effect_runtime_result

    def without_confirmation(method, payload, **kwargs):
        result = invoke(method, payload, **kwargs)
        if payload.get("projection_readback") is not None:
            result.get("metadata", {}).pop("projection_readback", None)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(local_authority, "effect_runtime_result", without_confirmation)
        result = provider_projection.settle_canonical_todo_projection(
            {"status": "applied", "changed": True}, **args
        )
    assert result["status"] == "applied"
    assert result["projection_delivery"] == "pending"
    assert result["projection_outbox"]["retry_business_mutation"] is False
    assert first["provider_revision"] in state.read_text()
    replay = provider_projection.project_current_canonical_todos(**args)
    assert replay["status"] == "current"
    assert replay["provider_revision"] == first["provider_revision"]
