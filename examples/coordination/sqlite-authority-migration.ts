/**
 * Operator entry point for the explicit V1 to V2 SQLite authority migration.
 *
 * Qualification: `--directory` must point at the runtime directory that owns
 * the goal's `authority/<profile>` database. The migration reads that one
 * database, proves every retained commit while writing the bounded state log,
 * and swaps tables only inside the same transaction. `--expected-identity`
 * additionally refuses any database whose stored incarnation is not the one
 * the operator names, so a renamed or recreated goal directory cannot be
 * rewritten by accident. Nothing else in the runtime is touched, so a planned
 * run is always safe and an executed run is reversible by restoring the
 * pre-migration database copy the operator keeps.
 */
import {existsSync, writeFileSync} from "node:fs";
import {parseArgs} from "node:util";

import {migrateSqliteAuthorityStoreV1ToV2} from
  "../../loopx/control_plane/coordination/sqlite_authority_migration.ts";

const {values: options} = parseArgs({options: {
  directory: {type: "string"}, "goal-id": {type: "string"}, execute: {type: "boolean", default: false},
  "expected-identity": {type: "string"}, format: {type: "string", default: "json"},
  output: {type: "string"},
}});

const report = (reason: string): {schema_version: string; status: string; reason_code: string; reason: string} =>
  ({schema_version: "loopx_sqlite_authority_migration_cli_v0", status: "failed",
    reason_code: "migration_invocation_invalid", reason});

const directory = options.directory;
const goalId = options["goal-id"];
const expectedIdentity = options["expected-identity"];
const result = directory === undefined || goalId === undefined
  ? report("--directory and --goal-id are required")
  : migrateSqliteAuthorityStoreV1ToV2(directory, goalId, {
    execute: options.execute === true,
    ...(expectedIdentity === undefined ? {} : {expectedIdentity}),
  });

const payload: Record<string, unknown> = {...result,
  database_present: directory === undefined ? false : existsSync(directory)};
if (options.output !== undefined) writeFileSync(options.output, `${JSON.stringify(payload, null, 2)}\n`);
if (options.format === "markdown") {
  const lines = [`# SQLite authority migration`, "", `- status: ${String(payload.status)}`,
    ...(payload.reason_code === undefined ? [] : [`- reason_code: ${String(payload.reason_code)}`,
      `- reason: ${String(payload.reason)}`]),
    ...(payload.commits === undefined ? [] : [`- commits: ${String(payload.commits)}`,
      `- checkpoints: ${String(payload.checkpoints ?? "unknown")}`]),
    ...(payload.sequence_digest === undefined ? [] : [`- sequence_digest: ${String(payload.sequence_digest)}`]),
    ...(payload.database_bytes_before === undefined ? [] :
      [`- database_bytes_before: ${String(payload.database_bytes_before)}`,
        `- database_bytes_after: ${String(payload.database_bytes_after ?? "unchanged")}`]), ""];
  process.stdout.write(lines.join("\n"));
} else process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
if (payload.status === "failed") process.exit(1);
