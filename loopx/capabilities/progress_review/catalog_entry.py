from __future__ import annotations

from typing import Any

PROGRESS_REVIEW_CATALOG_ENTRY: dict[str, Any] = {
    "id": "progress-review-sentinel",
    "origin": "builtin",
    "visibility": "public",
    "provider_id": "loopx-core",
    "documentation": {
        "source_root": "loopx/capabilities/progress_review",
        "site_root": "capabilities/progress-review",
        "canonical": "README.md",
    },
    "title": "Scoped progress-review sentinel",
    "status": "active-preview",
    "default_enabled": False,
    "real_world_anchor": (
        "per-heartbeat typed drift receipts from an external bounded reviewer of "
        "scoped file deltas"
    ),
    "user_value": (
        "Surface busy-but-off-goal work rounds earlier than the periodic review, "
        "using the existing autonomous replan obligation instead of new authority."
    ),
    "entry_command": (
        "loopx configure-goal --goal-id <goal-id> --progress-review-mode shadow"
    ),
    "commands": [
        {
            "command": (
                "loopx configure-goal --goal-id <goal-id> --progress-review-mode "
                "shadow --execute"
            ),
            "purpose": "Record typed review receipts without any control effect.",
            "write_boundary": "goal registry policy only",
        },
        {
            "command": (
                "loopx configure-goal --goal-id <goal-id> --progress-review-mode "
                "assist --progress-review-drift-threshold 2 "
                "--progress-review-contract-revision <basis-sha256> --execute"
            ),
            "purpose": (
                "Let consecutive completed drift receipts bound to the pinned goal "
                "contract become the existing autonomous replan obligation."
            ),
            "write_boundary": "goal registry policy only; no pause or gate authority",
        },
        {
            "command": (
                "loopx-jev drift init --state-dir <dir> --config <config> "
                "--workspace <repo> --basis <basis> --runtime-root <runtime> "
                "--path <file>"
            ),
            "purpose": "Bind the optional observer to a Goal, scoped files and runtime.",
            "write_boundary": "observer-private state; receipts under goal runtime",
        },
        {
            "command": (
                "loopx-jev sentinel compare --matrix <matrix.json> --responses <dir> "
                "--output <receipt.json>"
            ),
            "purpose": (
                "Replay the committed comparison matrix: baseline fuse versus "
                "external review, first-flag round and false flags per sequence."
            ),
            "write_boundary": "temporary repositories and one comparison receipt",
        },
    ],
    "implemented_protocols": [
        {
            "schema_version": "progress_review_policy_v0",
            "module": "loopx.capabilities.progress_review.policy",
            "doc": "loopx/capabilities/progress_review/README.md",
        },
        {
            "schema_version": "progress_review_receipt_v0",
            "module": "loopx.capabilities.progress_review.receipt",
            "doc": "loopx/capabilities/progress_review/README.md",
        },
        {
            "schema_version": "external_progress_review_trigger_v0",
            "module": "loopx.control_plane.work_items.external_progress_review",
            "doc": "loopx/capabilities/progress_review/README.md",
        },
    ],
    "smokes": ["python3 examples/progress-review-sentinel-smoke.py"],
    "docs": [
        "loopx/capabilities/progress_review/README.md",
        "loopx/capabilities/progress_review/README.zh-CN.md",
        "packages/loopx-jev/DRIFT_SHADOW.md",
    ],
    "boundaries": [
        "Default-off. shadow records receipts only; assist may raise the existing autonomous replan obligation and nothing else.",
        "The core never calls a model, never reads a raw delta and never imports the optional observer package; it consumes typed receipts through one schema.",
        "Receipts never overwrite or supplement the Agent's own typed progress_observation; they are a sibling record keyed by turn identity.",
        "unknown, abstained, failed, ambiguous, identity-conflicting and missing receipts break a drift streak; only the newest still-pending evaluations are skipped, and never counted.",
        "assist requires the goal policy to pin the observer basis revision; receipts bound to any other revision are stale history, never current evidence, and an acknowledged autonomous replan re-arms the trigger.",
        "The core recomputes each receipt's drift booleans from its typed judgments and rejects a receipt whose booleans disagree; a writer cannot assert drift without evidence.",
        "assist changes the Agent's work contract (a required obligation with an acknowledgement); it is not a passive recommendation, even though it grants no new authority.",
        "No user gate, quota pause, Turn settlement or Goal acceptance authority is granted; escalation legs remain future work.",
        "Model inference runs in the observer's separate consumer process, outside every core write lock and transaction.",
    ],
    "next_real_step": (
        "Run one Goal in shadow, label its receipts, and compare first-flag rounds "
        "against the typed fuse before enabling assist."
    ),
}
