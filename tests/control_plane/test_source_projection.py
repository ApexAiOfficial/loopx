"""The production Python bridge must not sanitize corruption into empty evidence."""
import pytest

from loopx.control_plane.coordination.local_authority_shadow_projection import (
    ProjectionValueError, canonical_bytes, todo_partition_projection,
)
from loopx.control_plane.coordination.runtime_shadow import build_todo_runtime_shadow_projection

TODO = {"schema_version": "todo_item_v0", "todo_id": "a", "role": "agent", "status": "open",
        "done": False, "text": "Capture exact state", "archive_state": "active", "source_section": "Agent Todo"}


@pytest.mark.parametrize("todos", [None, {}, [None], [{}], [TODO, TODO]])
def test_full_capture_rejects_incomplete_or_ambiguous_records(todos):
    with pytest.raises(ValueError):
        build_todo_runtime_shadow_projection(goal_id="goal", todos=todos)


@pytest.mark.parametrize("leases", [{}, [None], [{}], [{"todo_id": "old", "goal_id": "other"}],
                                    [{"todo_id": "old"}, {"todo_id": "old"}]])
def test_retained_history_is_validated_before_membership_filter(leases):
    with pytest.raises(ValueError):
        build_todo_runtime_shadow_projection(goal_id="goal", todos=[TODO], leases=leases)


@pytest.mark.parametrize("value", [2**53, 2**53 + 1, -(2**53 + 1), 1.0])
def test_exact_number_boundary_rejects_before_runtime_transport(monkeypatch, value):
    import loopx.control_plane.effect_runtime as runtime

    def unexpected(*args, **kwargs):
        pytest.fail("unsafe source number crossed the Python/TS boundary")

    monkeypatch.setattr(runtime, "effect_runtime_result", unexpected)
    with pytest.raises(ProjectionValueError):
        build_todo_runtime_shadow_projection(goal_id="goal", todos=[TODO],
                                            leases=[{"todo_id": "a", "version": value}])
    with pytest.raises(ProjectionValueError):
        canonical_bytes({"nested": [value]})


def test_partition_and_full_capture_share_one_record_contract():
    source = [{**TODO, "succession_evaluation": {"query_only": True}}]
    partition = todo_partition_projection(handoff_mode="legacy", todos=source)
    full = build_todo_runtime_shadow_projection(goal_id="goal", handoff_mode="legacy", todos=source)
    assert partition == {key: full[key] for key in ("handoff_mode", "todos")}
    assert "succession_evaluation" in source[0]
    assert "succession_evaluation" not in full["todos"][0]
