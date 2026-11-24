#!/usr/bin/env python3
"""Exercise the Frontstage stargazer fetch helper without live credentials."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FETCH = ROOT / "scripts" / "fetch-github-stargazers.sh"


FAKE_GH = r"""#!/usr/bin/env bash
set -euo pipefail

mode="${FAKE_GH_MODE:-success}"
temp_root="${RUNNER_TEMP:-/tmp}"
counter="$temp_root/fake-gh-calls"
calls=0
if [[ -f "$counter" ]]; then
  calls="$(cat "$counter")"
fi
calls=$((calls + 1))
printf '%s\n' "$calls" > "$counter"

if [[ "$mode" == "deny" ]]; then
  echo "gh: Resource not accessible by integration (HTTP 403)" >&2
  exit 1
fi
if [[ "$*" == *"${GH_TOKEN:?}"* ]]; then
  echo "credential was passed as a command argument" >&2
  exit 2
fi
if [[ "$mode" == "flaky" && "$calls" -le "${FAKE_GH_FAILED_CALLS:-1}" ]]; then
  echo "unexpected end of JSON input" >&2
  exit 1
fi
if [[ "$*" == *"--paginate --slurp"* ]]; then
  [[ "$*" == *"Accept: application/vnd.github.star+json"* ]]
  [[ "$*" == *"repos/example/loopx/stargazers?per_page=100"* ]]
  if [[ "$mode" == "empty" ]]; then
    marker="$temp_root/fake-gh-empty-served"
    if [[ ! -f "$marker" ]]; then
      : > "$marker"
      exit 0
    fi
  fi
  printf '%s\n' '[[{"starred_at":"2026-08-17T01:02:03Z"},{"starred_at":"2026-08-18T04:05:06Z"}]]'
else
  [[ "$*" == *"repos/example/loopx"* ]]
  [[ "$*" == *"--jq .stargazers_count"* ]]
  printf '%s\n' '2'
fi
"""


EXPECTED_ROWS = [
    {"starred_at": "2026-08-17T01:02:03Z"},
    {"starred_at": "2026-08-18T04:05:06Z"},
]


def run_fetch(root: Path, *, token: str | None, mode: str = "success") -> subprocess.CompletedProcess[str]:
    fake_bin = root / "bin"
    fake_bin.mkdir(exist_ok=True)
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(FAKE_GH, encoding="utf-8")
    fake_gh.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["RUNNER_TEMP"] = str(root)
    env["LOOPX_STARGAZER_RETRY_DELAY_SECONDS"] = "0"
    env["FAKE_GH_MODE"] = mode
    if token is None:
        env.pop("GH_TOKEN", None)
    else:
        env["GH_TOKEN"] = token
    return subprocess.run(
        [
            str(FETCH),
            "example/loopx",
            str(root / "stargazers.json"),
            str(root / "stargazers-count"),
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def gh_calls(root: Path) -> int:
    return int((root / "fake-gh-calls").read_text(encoding="utf-8").strip())


def assert_complete_snapshot(root: Path) -> None:
    rows = json.loads((root / "stargazers.json").read_text(encoding="utf-8"))
    assert rows == EXPECTED_ROWS, rows
    assert (root / "stargazers-count").read_text(encoding="utf-8") == "2\n"


def main() -> int:
    synthetic_token = "-".join(("test", "only"))
    with tempfile.TemporaryDirectory(prefix="loopx-stargazer-fetch-") as tmp:
        root = Path(tmp)
        success = run_fetch(root, token=synthetic_token)
        assert success.returncode == 0, success.stderr
        assert_complete_snapshot(root)
        assert gh_calls(root) == 3, "a healthy fetch reads both counts and one page set"
        assert "Retrying star history read" not in success.stderr

    with tempfile.TemporaryDirectory(prefix="loopx-stargazer-missing-") as tmp:
        missing = run_fetch(Path(tmp), token=None)
        assert missing.returncode != 0
        assert "Missing star-history credential" in missing.stderr

    with tempfile.TemporaryDirectory(prefix="loopx-stargazer-denied-") as tmp:
        root = Path(tmp)
        denied = run_fetch(root, token=synthetic_token, mode="deny")
        assert denied.returncode != 0
        assert "HTTP 403" in denied.stderr
        assert synthetic_token not in denied.stderr
        assert gh_calls(root) == 1, "an authorization failure must not be retried"
        assert not (root / "stargazers.json").exists()

    # A transient transport failure used to abort the whole Pages deployment,
    # because `set -e` ended the step on the first non-zero `gh` exit. It must
    # now cost one bounded retry and still publish a complete snapshot.
    with tempfile.TemporaryDirectory(prefix="loopx-stargazer-flaky-") as tmp:
        root = Path(tmp)
        flaky = run_fetch(root, token=synthetic_token, mode="flaky")
        assert flaky.returncode == 0, flaky.stderr
        assert "Retrying star history read" in flaky.stderr
        assert "unexpected end of JSON input" in flaky.stderr
        assert_complete_snapshot(root)
        assert gh_calls(root) == 4, "the retried read must be the only extra call"

    # GitHub can also answer 2xx with an empty body, which surfaces as the same
    # "unexpected end of JSON input" failure. Retry that read instead of
    # treating the empty page set as a complete snapshot.
    with tempfile.TemporaryDirectory(prefix="loopx-stargazer-empty-") as tmp:
        root = Path(tmp)
        empty = run_fetch(root, token=synthetic_token, mode="empty")
        assert empty.returncode == 0, empty.stderr
        assert "Retrying star history read" in empty.stderr
        assert_complete_snapshot(root)
        assert gh_calls(root) == 4, "an empty page set must be retried, not accepted"

    print("frontstage-stargazer-fetch-smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
