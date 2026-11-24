"""A bounded coverage caveat is supporting evidence, not a project risk."""

from __future__ import annotations

import pytest

from loopx.capabilities.periodic_report import (
    build_periodic_report_document,
    build_project_progress_periodic_report_source,
)
from loopx.capabilities.periodic_report.pending_intent import _cadence_coverage_fact
from loopx.presentation.renderers.periodic_report_markdown import (
    render_periodic_report_markdown,
)

GOAL_ID = "coverage-fact-fixture"
OBSERVED_AT = "2026-09-11T10:00:00Z"
CADENCE_WINDOW = {
    "window_id": "cadence-2026-09-11",
    "start_at": "2026-09-04T10:00:00Z",
    "due_at": OBSERVED_AT,
}
COVERAGE_TITLE = "本期证据覆盖范围"
RISK_TITLE = "Owner gate blocks the next merge"


def _coverage_item(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "item_id": "calendar_coverage",
        "title": COVERAGE_TITLE,
        "summary": "仅核对当前可读的本 Agent 任务记录；空结果不能证明本期没有进展。",
        "content_kind": "coverage",
        "visibility": "supporting",
        "value_rank": 90,
        "source_ref": "cadence:cadence-2026-09-11",
    }
    item.update(overrides)
    return item


def _risk_item() -> dict[str, object]:
    return {
        "item_id": "risk_owner_gate",
        "title": RISK_TITLE,
        "summary": "The maintainer decision is still outstanding.",
        "content_kind": "risk",
        "value_rank": 30,
        "source_ref": "todo:todo_owner_gate",
    }


def _projection(items: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "periodic_report_project_progress_projection_v0",
        "goal_id": GOAL_ID,
        "observed_at": OBSERVED_AT,
        "language": "zh-CN",
        "items": items,
    }


def test_cadence_coverage_fact_is_supporting_coverage_not_a_risk() -> None:
    fact = _cadence_coverage_fact(CADENCE_WINDOW)

    assert fact["fact_id"] == "calendar_coverage"
    assert fact["content_kind"] == "coverage"
    assert fact["visibility"] == "supporting"
    assert fact["status"] == "unknown"
    assert fact["source_ref"] == "cadence:cadence-2026-09-11"


def test_coverage_item_leaves_the_risks_section_and_keeps_a_real_risk() -> None:
    source = build_project_progress_periodic_report_source(
        _projection([_risk_item(), _coverage_item()])
    )
    sections = {section["section_id"]: section for section in source["sections"]}

    coverage_items = [
        item
        for item in sections["supporting_evidence"]["items"]
        if item["item_id"] == "calendar_coverage"
    ]
    risk_items = [item for item in sections["risks"]["items"]]

    assert [item["content_kind"] for item in coverage_items] == ["coverage"]
    assert [item["visibility"] for item in coverage_items] == ["supporting"]
    assert [item["title"] for item in risk_items] == [RISK_TITLE]
    assert [item["content_kind"] for item in risk_items] == ["risk"]


def test_rendered_report_keeps_the_caveat_out_of_the_risks_section() -> None:
    source = build_project_progress_periodic_report_source(
        _projection([_risk_item(), _coverage_item()])
    )
    document = build_periodic_report_document(
        title="项目周报",
        generated_at=OBSERVED_AT,
        period_window={"start_at": "2026-09-04T10:00:00Z", "end_at": OBSERVED_AT},
        profile={"profile_id": "weekly_progress", "profile_version": "v1"},
        sources=[source],
        editorial={"language": "zh-CN"},
    )
    content = render_periodic_report_markdown(document)["content"]

    risks_at = content.index("风险与阻塞")
    supporting_at = content.index("支撑证据")
    coverage_at = content.index(COVERAGE_TITLE)
    assert risks_at < supporting_at < coverage_at
    assert RISK_TITLE in content[risks_at:supporting_at]
    assert COVERAGE_TITLE not in content[risks_at:supporting_at]


def test_primary_coverage_item_is_rejected_by_the_material_contract() -> None:
    with pytest.raises(ValueError, match="visibility must be supporting for coverage"):
        build_project_progress_periodic_report_source(
            _projection([_coverage_item(visibility="primary")])
        )
