"""The model never sees goal or case identity; only the operator basis and material."""

from __future__ import annotations

from loopx_jev.progress import MODEL_BASIS_FIELDS, build_request
from loopx_jev.protocol import request_bytes

SNAPSHOT = {
    "schema": "jev_progress_input_v0",
    "scenario": "progress_review",
    "source": {"owner": "scoped_checkpoint_capture", "revision": "a" * 64},
    "facts": {"work_summary": "x", "history_available": True},
}


def _basis(goal_id: str) -> dict:
    return {
        "goal_id": goal_id,
        "objective": "Make deliver() retry one transient TimeoutError",
        "acceptance": ["One TimeoutError is retried once"],
        "evidence": [{"ref": "captured-workspace-delta", "text": "+RETRY = 1", "origin": "host", "sha256": "b" * 64}],
        "basis_origin": "explicit_operator_study_basis_not_completion_authority",
    }


def test_requests_are_byte_identical_across_goal_identities() -> None:
    drift_named = build_request(SNAPSHOT, _basis("sentinel-drift_rename_constants"), "m")
    neutral = build_request(SNAPSHOT, _basis("sentinel-3f9a1c2e7b6d4a80"), "m")
    assert request_bytes(drift_named) == request_bytes(neutral)
    assert set(drift_named["state"]["goal_basis"]) <= set(MODEL_BASIS_FIELDS)
    flat = request_bytes(drift_named).decode()
    assert "goal_id" not in flat and "sentinel-" not in flat and "basis_origin" not in flat
