import { SqliteAuthorityStore } from "../../loopx/control_plane/coordination/sqlite_authority_store.ts";
import { authorityStoreCommitFixture } from "./authority_store_conformance.ts";
import {createRequire} from "node:module";

const [directory, operation, revision] = process.argv.slice(2);
if (operation === "crash-before" || operation === "crash-after" || operation === "capacity-full") {
  // Instrument only the disposable child. Real SQL and process termination
  // remain in the production entrypoint; no fault hooks enter product code.
  const {DatabaseSync} = createRequire(import.meta.url)("node:sqlite");
  const original = DatabaseSync.prototype.exec;
  let commits = 0, begins = 0;
  DatabaseSync.prototype.exec = function(sql: string) {
    if (sql === "BEGIN IMMEDIATE" && ++begins === 2 && operation === "capacity-full") {
      const pages = this.prepare("PRAGMA page_count").get().page_count;
      this.exec(`PRAGMA max_page_count=${pages}`);
    }
    if (sql === "COMMIT" && ++commits === 2 && operation.startsWith("crash-")) {
      if (operation === "crash-before") process.kill(process.pid, "SIGKILL");
      const result = original.call(this, sql);
      process.kill(process.pid, "SIGKILL"); return result;
    }
    return original.call(this, sql);
  };
}
const store = new SqliteAuthorityStore(directory!, "goal");
await new Promise<void>(resolve => process.stdout.write("ready\n", () => resolve()));
for await (const _chunk of process.stdin) {
  const input = authorityStoreCommitFixture(revision === "null" ? null : revision!, operation!, 1, 1);
  if (operation === "capacity-full") input.next_projection.capacity_padding = "x".repeat(1024 * 1024);
  const result = await store.commitAuthority(input);
  if (operation === "lost-response" && result.status === "applied") process.exit(23);
  process.stdout.write(`${JSON.stringify(result)}\n`);
  break;
}
