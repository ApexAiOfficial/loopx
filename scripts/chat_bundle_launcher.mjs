#!/usr/bin/env node
// Build entry for the generated Chat frontend.
//
// `npm run build:chat` must work wherever Node runs, not only where the POSIX
// `python3` name exists: supported Windows installations commonly provide
// `python.exe` alone, and a `python3.exe` App Execution Alias stub is not a
// runnable interpreter. Resolve one compatible interpreter here and keep every
// build rule in the shared `scripts/chat_bundle.py` builder.

import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const BUILDER = path.join(ROOT, "scripts", "chat_bundle.py");
const PROBE = "import sys; raise SystemExit(sys.version_info < (3, 11))";
const WINDOWS = process.platform === "win32";

function recordedInterpreter() {
  const file = path.join(ROOT, ".loopx-python");
  if (!existsSync(file)) return null;
  const value = readFileSync(file, "utf8").split("\n")[0].trim();
  return value.length > 0 ? value : null;
}

// Discovery order matches the documented LoopX launcher contract for this
// checkout: explicit override, installer-recorded interpreter, project
// environment, then the platform names Node and npm users already have.
function candidates() {
  const found = [];
  const explicit = (process.env.LOOPX_PYTHON ?? "").trim();
  if (explicit) {
    found.push({ argv: [explicit], label: "LOOPX_PYTHON", authoritative: true });
  }
  const recorded = recordedInterpreter();
  if (recorded) found.push({ argv: [recorded], label: ".loopx-python" });
  found.push({
    argv: [
      path.join(ROOT, ".venv", WINDOWS ? "Scripts/python.exe" : "bin/python"),
    ],
    label: "the repository .venv",
  });
  for (const name of ["python3", "python"]) {
    found.push({ argv: [name], label: name });
  }
  if (WINDOWS) found.push({ argv: ["py", "-3"], label: "the py launcher" });
  return found;
}

function compatible(argv) {
  const probe = spawnSync(argv[0], [...argv.slice(1), "-c", PROBE], {
    cwd: ROOT,
    stdio: "ignore",
    windowsHide: true,
  });
  return probe.status === 0;
}

function select() {
  for (const candidate of candidates()) {
    if (compatible(candidate.argv)) return candidate;
    if (candidate.authoritative) {
      console.error(
        "LOOPX_PYTHON is set but does not resolve to a Python 3.11+ interpreter: " +
          candidate.argv[0],
      );
      process.exit(2);
    }
  }
  console.error(
    "No Python 3.11+ interpreter was found for the Chat frontend build.\n" +
      "Checked LOOPX_PYTHON, .loopx-python, the repository .venv, " +
      `python3/python on PATH${WINDOWS ? " and the py launcher" : ""}.\n` +
      "Install Python 3.11+ (or set LOOPX_PYTHON) and rerun npm run build:chat.",
  );
  process.exit(2);
}

const python = select();
console.error(
  `[chat-bundle] building with ${python.argv.join(" ")} (${python.label})`,
);
const built = spawnSync(
  python.argv[0],
  [...python.argv.slice(1), BUILDER, ...process.argv.slice(2)],
  { cwd: ROOT, stdio: "inherit", windowsHide: true },
);
if (built.error) {
  console.error(`Unable to run ${python.argv[0]}: ${built.error.message}`);
  process.exit(2);
}
process.exit(built.status ?? 1);
