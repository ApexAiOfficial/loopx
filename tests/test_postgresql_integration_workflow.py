"""Thin pytest: the PostgreSQL workflow keeps the real-server path qualified."""

from pathlib import Path

import yaml

from loopx.control_plane.testing.authority_e2e_ladder import LADDER_ROWS


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "postgresql-integration.yml"
WORKFLOW_TEXT = WORKFLOW_PATH.read_text(encoding="utf-8")
WORKFLOW = yaml.safe_load(WORKFLOW_TEXT)
JOB = WORKFLOW["jobs"]["postgresql-authority"]
RELEVANT_PATHS = (
    ".github/workflows/postgresql-integration.yml",
    "loopx/control_plane/**",
    "tests/control_plane_ts/**",
    "package.json",
    "package-lock.json",
)


def _triggers() -> dict:
    # PyYAML resolves the bare `on:` key to True.
    return WORKFLOW.get("on") or WORKFLOW[True]


def _steps() -> list[dict]:
    return JOB["steps"]


def _step_running(fragment: str) -> dict:
    matches = [step for step in _steps() if fragment in step.get("run", "")]
    assert len(matches) == 1, (fragment, len(matches))
    return matches[0]


def _step_named(name: str) -> dict:
    matches = [step for step in _steps() if step.get("name") == name]
    assert len(matches) == 1, (name, len(matches))
    return matches[0]


def test_workflow_qualifies_the_authority_paths() -> None:
    triggers = _triggers()
    assert "workflow_dispatch" in triggers
    for event in ("pull_request", "push"):
        for path in RELEVANT_PATHS:
            assert path in triggers[event]["paths"], (event, path)
    assert triggers["push"]["branches"] == ["main"]


def test_workflow_stays_read_only_and_secret_free() -> None:
    assert WORKFLOW["permissions"] == {"contents": "read"}
    assert "secrets." not in WORKFLOW_TEXT
    assert "pull_request_target" not in WORKFLOW_TEXT


def test_workflow_runs_a_pinned_bounded_disposable_server() -> None:
    assert JOB["runs-on"] == "ubuntu-latest"
    assert JOB["timeout-minutes"] <= 10
    service = JOB["services"]["postgres"]
    assert service["image"] == "postgres:16.15"
    assert "pg_isready" in service["options"]
    assert service["env"]["POSTGRES_DB"] == "loopx_store"


def test_workflow_uses_the_canonical_ladder_row() -> None:
    rows = {row.id: row for row in LADDER_ROWS}
    row = rows["s2b.postgresql_conformance_live"]
    assert row.gate == "env:postgresql"
    step = _step_running("authority_e2e_ladder")
    assert "--row s2b.postgresql_conformance_live" in step["run"]
    assert "--report-json postgresql-conformance-report.json" in step["run"]
    assert step["env"]["LOOPX_TEST_POSTGRES_URL"].endswith("/loopx_store")


def test_workflow_asserts_the_service_path_by_name() -> None:
    step = _step_running("npm run test:postgresql-authority-service")
    assert step["env"]["LOOPX_TEST_POSTGRES_SERVICE_URL"].endswith("/loopx_service")
    assert step["env"]["LOOPX_TEST_POSTGRES_URL"].endswith("/loopx_store")
    # The suite keeps a placeholder test that stays green without a URL, so the
    # real-server case must be required by name: a skip is an evidence gap.
    assert "grep -Fq" in step["run"]
    assert (
        "PostgreSQL service admits an authorized tenant and rotates a restored incarnation"
        in step["run"]
    )
    # A renamed or dropped script is a coverage loss, not a silent skip.
    installed = _step_named("Assert the service admission suite is available")
    assert "test:postgresql-authority-service" in installed["run"]


def test_workflow_keeps_bounded_evidence() -> None:
    uploads = [step for step in _steps() if "upload-artifact" in str(step.get("uses", ""))]
    assert len(uploads) == 1
    paths = uploads[0]["with"]["path"]
    assert "postgresql-conformance-report.json" in paths
    assert "postgresql-service-admission.log" in paths
