"""Run one WideSearch case under baseline (native Codex Goal) or treatment
(LoopX-guided) arm, producing a fresh final_answer.md in an isolated workspace.

Verifier is intentionally NOT part of this repo: it runs as the official
WideSearch evaluator inside a pier task (sandboxed, gold hidden from the agent)
for the local real-sandbox path, matching the deepswe infrastructure. This file
reuses the shipped native Goal runtime (no second implementation):
  from loopx.capabilities.benchmark_toolkit.native_codex_goal import ...
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from tasks import answer_is_fresh, fresh_workspace, prepare_case, stamp_run_start

REPO_ROOT = Path(__file__).resolve().parents[2]
_PROVIDER_CREDENTIAL_ENV_KEY = "ARK_OPENAI_API_KEY"
_PROVIDER_BASE_URL_ENV_KEY = "ARK_OPENAI_BASE_URL"
_PROVIDER_SENTINEL_ENV_KEY = "LOOPX_MODEL_PROVIDER_SENTINEL"
_PROVIDER_SENTINEL_VALUE = "runner-owned-gateway-no-upstream-secret"
_PROVIDER_ID = "loopx_runner_gateway"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.capabilities.benchmark_toolkit.native_codex_goal import (  # noqa: E402
    NativeGoalConfig,
    compact_native_goal_receipt,
    run_native_goal_process_until_terminal,
)
from loopx.capabilities.benchmark_toolkit.native_codex_isolation import (  # noqa: E402
    NativeCodexIsolationError,
    build_native_codex_isolation_envelope,
    rebase_native_codex_loopx_workspace_state,
)
from loopx.capabilities.benchmark_toolkit.native_codex_profile import (  # noqa: E402
    NativeCodexProfile,
    install_native_codex_profile,
    native_codex_app_server_shell_policy_args,
    native_codex_profile_environment,
)
from loopx.capabilities.benchmark_toolkit.provider_gateway import (  # noqa: E402
    serve_runner_owned_provider_gateway,
)


def _objective(case_id: str, workspace: Path, instruction: str, treatment: bool) -> str:
    common = (
        f"Write the final markdown table to {workspace}/final_answer.md and stop. "
        "Use web_search / web_fetch to gather facts from the web."
    )
    if treatment:
        return (
            "Use the installed LoopX skill (/loopx) to start a goal for the benchmark "
            "task in this workspace, then complete the task through LoopX's guided "
            "control (follow its todos and state writebacks). "
            f"Task instruction is in instruction.md: {instruction} {common}"
        )
    return (
        "Complete the benchmark task described in instruction.md inside this "
        f"workspace. {common}"
    )


def _app_server_command(
    *,
    codex_bin: str,
    enable_web_search: bool,
    gateway_base_url: str,
    shell_policy_args: tuple[str, ...],
) -> list[str]:
    """Build the app-server Goal command with hosted Responses API compatibility.

    The codex app-server emits a ``multi_agent_v1`` dynamic-tool namespace by
    default; some hosted Responses endpoints reject ``namespace`` tool types.
    Disabling the multi-agent feature keeps the Goal tool surface minimal and
    provider-neutral while preserving the goal tools (get/create/update_goal)
    that the benchmark needs. Web search is toggled independently because some
    hosted endpoints also reject the ``external_web_access`` web_search field.
    """

    command = [
        codex_bin,
        "app-server",
        "--listen",
        "stdio://",
        "--enable",
        "goals",
        "-c",
        "features.multi_agent=false",
        "-c",
        f'model_provider="{_PROVIDER_ID}"',
        "-c",
        f'model_providers.{_PROVIDER_ID}.name="runner-owned-gateway"',
        "-c",
        f"model_providers.{_PROVIDER_ID}.base_url={json.dumps(gateway_base_url)}",
        "-c",
        (
            f"model_providers.{_PROVIDER_ID}.env_key="
            f"{json.dumps(_PROVIDER_SENTINEL_ENV_KEY)}"
        ),
        "-c",
        f'model_providers.{_PROVIDER_ID}.wire_api="responses"',
        *shell_policy_args,
    ]
    command += [
        "-c",
        "tools.web_search=true" if enable_web_search else "tools.web_search=false",
    ]
    return command


def _app_server_environment(
    profile: NativeCodexProfile,
    environ: dict[str, str],
) -> dict[str, str]:
    """Build the credential-free environment visible inside native isolation."""

    profile_environment = native_codex_profile_environment(
        profile,
        base_env=environ,
    )
    forbidden = {
        _PROVIDER_BASE_URL_ENV_KEY,
        _PROVIDER_CREDENTIAL_ENV_KEY,
    }.intersection(profile_environment)
    if forbidden:
        raise ValueError("provider credential authority must stay outside app-server")
    return {
        **profile_environment,
        _PROVIDER_SENTINEL_ENV_KEY: _PROVIDER_SENTINEL_VALUE,
    }


def _runner_provider_authority(environ: dict[str, str]) -> tuple[str, str]:
    base_url = str(environ.get(_PROVIDER_BASE_URL_ENV_KEY) or "").strip()
    credential = str(environ.get(_PROVIDER_CREDENTIAL_ENV_KEY) or "")
    if not base_url or not credential.strip():
        raise RuntimeError("widesearch_runner_provider_authority_missing")
    return base_url, credential


def run_case(
    *,
    case_id: str,
    arm: str,
    data_root: Path,
    timeout_sec: int,
    enable_web_search: bool = True,
) -> dict[str, Any]:
    if sys.platform != "linux":
        raise RuntimeError("widesearch_native_isolation_unavailable_use_pier")
    raw = data_root / "widesearch.jsonl"
    gold_dir = data_root / "gold"
    cases_root = data_root / "cases"
    run_id = f"{case_id}-{arm}-{time.strftime('%Y%m%d-%H%M%S')}"

    prepare_case(raw=raw, gold_dir=gold_dir, cases_root=cases_root, case_id=case_id)
    workspace = fresh_workspace(cases_root=cases_root, case_id=case_id, run_id=run_id)
    started_at = stamp_run_start(workspace)
    instruction = (workspace / "instruction.md").read_text(encoding="utf-8")

    model = os.environ.get("ARK_OPENAI_MODEL", "deepseek-v4-flash-ga-260731")
    provider_base_url, provider_credential = _runner_provider_authority(
        dict(os.environ)
    )
    codex_bin = os.environ.get("CODEX_BIN", "codex")

    with (
        tempfile.TemporaryDirectory(prefix="loopx-widesearch-profile-") as profile_dir,
        tempfile.TemporaryDirectory(prefix="loopx-widesearch-worker-") as worker_dir,
    ):
        profile = install_native_codex_profile(
            REPO_ROOT,
            Path(profile_dir),
            base_env=os.environ,
        )
        with serve_runner_owned_provider_gateway(
            upstream_base_url=provider_base_url,
            upstream_bearer_token=provider_credential,
        ) as gateway:
            shell_policy_args = native_codex_app_server_shell_policy_args(
                excluded_env_keys=(_PROVIDER_SENTINEL_ENV_KEY,)
            )
            app_server_command = _app_server_command(
                codex_bin=codex_bin,
                enable_web_search=enable_web_search,
                gateway_base_url=gateway.base_url,
                shell_policy_args=shell_policy_args,
            )
            try:
                envelope = build_native_codex_isolation_envelope(
                    executable=codex_bin,
                    process_args=app_server_command[1:],
                    work_dir=Path(worker_dir),
                    private_root=gold_dir,
                    workspace_source=workspace,
                    profile_root=profile.root,
                )
            except NativeCodexIsolationError as exc:
                raise RuntimeError(
                    "widesearch_native_isolation_unavailable_use_pier"
                ) from exc
            if envelope.workspace_alias is None:
                raise RuntimeError("widesearch_native_workspace_alias_missing")
            runtime_workspace = envelope.workspace_alias
            rebase_native_codex_loopx_workspace_state(
                workspace,
                source_root=runtime_workspace,
                target_root=workspace,
            )
            restore_required = False
            try:
                rebase_native_codex_loopx_workspace_state(
                    workspace,
                    source_root=workspace,
                    target_root=runtime_workspace,
                )
                restore_required = True
                config = NativeGoalConfig(
                    cwd=str(runtime_workspace),
                    objective=_objective(
                        case_id,
                        runtime_workspace,
                        instruction,
                        treatment=(arm == "treatment"),
                    ),
                    task_instruction=instruction,
                    model=model,
                    effort=os.environ.get("CODEX_GOAL_EFFORT", "xhigh"),
                    approval_policy="never",
                    sandbox="danger-full-access",
                    required_skill_ids=profile.required_skill_ids,
                )
                turn = run_native_goal_process_until_terminal(
                    config,
                    codex_bin=codex_bin,
                    process_command=envelope.process_command,
                    process_env=_app_server_environment(profile, dict(os.environ)),
                    process_cwd=str(envelope.work_dir),
                    goal_timeout_sec=timeout_sec,
                )
            finally:
                if restore_required:
                    rebase_native_codex_loopx_workspace_state(
                        workspace,
                        source_root=runtime_workspace,
                        target_root=workspace,
                    )
            receipt = compact_native_goal_receipt(turn)
            receipt["provider_credential_boundary"] = {
                "schema_version": "runner_owned_provider_gateway_boundary_v0",
                "gateway_owner": "runner",
                "gateway_loopback_only": True,
                "upstream_credential_in_app_server": False,
                "ambient_home_exposed": False,
                "linux_user_mount_pid_namespace": True,
            }

    fresh, reason = answer_is_fresh(workspace, started_at)
    if not fresh:
        return {"status": "runner_invalid", "reason": reason, "receipt": receipt}
    return {
        "status": "completed",
        "final_answer": str(workspace / "final_answer.md"),
        "receipt": receipt,
        "arm": arm,
        "run_id": run_id,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--arm", choices=["baseline", "treatment"], required=True)
    p.add_argument("--case", default="ws_en_001")
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--timeout-sec", type=int, default=7200)
    p.add_argument(
        "--disable-web-search",
        action="store_true",
        help=(
            "Disable the native web_search tool in the app-server Goal config "
            "(some hosted Responses endpoints reject its external_web_access field)."
        ),
    )
    args = p.parse_args()
    outcome = run_case(
        case_id=args.case,
        arm=args.arm,
        data_root=args.data_root,
        timeout_sec=args.timeout_sec,
        enable_web_search=not args.disable_web_search,
    )
    print(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
    return 0 if outcome["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
