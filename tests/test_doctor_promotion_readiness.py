from __future__ import annotations

import json
from pathlib import Path

from loopx.control_plane.runtime.promotion_readiness import (
    PROMOTION_READINESS_CLASSIFICATION,
    PROMOTION_READINESS_RUNTIME_INDEX,
)
from loopx.doctor import latest_promotion_readiness_event


def test_latest_promotion_readiness_uses_utc_instant_across_offsets(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / PROMOTION_READINESS_RUNTIME_INDEX
    index_path.parent.mkdir(parents=True)
    rows = [
        {
            "classification": PROMOTION_READINESS_CLASSIFICATION,
            "generated_at": "2026-01-01T08:30:00+08:00",
            "recommended_action": "Older offset readiness.",
        },
        {
            "classification": PROMOTION_READINESS_CLASSIFICATION,
            "generated_at": "2026-01-01T01:00:00Z",
            "recommended_action": "Newer UTC readiness.",
        },
    ]
    index_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    result = latest_promotion_readiness_event(tmp_path)

    assert result["source"] == "runtime_release_ledger"
    assert result["generated_at"] == "2026-01-01T01:00:00Z"
    assert result["recommended_action"] == "Newer UTC readiness."
