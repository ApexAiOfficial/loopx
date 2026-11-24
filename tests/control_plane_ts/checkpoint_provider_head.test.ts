import assert from "node:assert/strict";
import {mkdtemp, rm} from "node:fs/promises";
import {writeFileSync, readFileSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import test from "node:test";
import {FileAuthorityStore} from "../../loopx/control_plane/coordination/file_authority_store.ts";
import {SqliteAuthorityStore} from "../../loopx/control_plane/coordination/sqlite_authority_store.ts";
import {sqliteRuntimeIdentity} from "../../loopx/control_plane/coordination/sqlite_runtime.ts";

const sqliteSkip = sqliteRuntimeIdentity().sqlite_authority_qualified
  ? false : "requires the qualified SQLite runtime";

for (const [name, Store] of [["File", FileAuthorityStore], ["SQLite", SqliteAuthorityStore]] as const) {
  test(`${name} checkpoint fence releases on failure without advancing provider revision`,
    {skip: name === "SQLite" && sqliteSkip}, async t => {
    const directory = await mkdtemp(join(tmpdir(), "checkpoint-fence-"));
    t.after(() => rm(directory, {recursive: true, force: true}));
    const store = new Store(directory, "goal");
    const created = await store.commitAuthority({expected_provider_revision: null, operation_id: "seed",
      next_projection: {value: 1}, events: [], receipts: []});
    assert.equal(created.status, "applied");
    const before = await store.loadAuthority();
    await assert.rejects(store.withCheckpointHead(() => {throw new Error("save failed");}), /save failed/);
    assert.deepEqual(await store.loadAuthority(), before);
    assert.equal(before.status, "loaded");
    if (before.status !== "loaded") return;
    const updated = await store.commitAuthority({expected_provider_revision: before.provider_revision,
      operation_id: "next", next_projection: {value: 2}, events: [], receipts: []});
    assert.equal(updated.status, "applied");
  });
}

test("SQLite concurrent requests in one runtime do not busy-wait on an awaiting checkpoint holder",
  {skip: sqliteSkip}, async t => {
  const directory = await mkdtemp(join(tmpdir(), "checkpoint-sqlite-loop-"));
  t.after(() => rm(directory, {recursive: true, force: true}));
  const a = new SqliteAuthorityStore(directory, "goal");
  const b = new SqliteAuthorityStore(directory, "goal");
  const other = new SqliteAuthorityStore(directory, "other-goal");
  await a.commitAuthority({expected_provider_revision: null, operation_id: "seed",
    next_projection: {value: 1}, events: [], receipts: []});
  let competing: Promise<unknown> | undefined;
  const order: string[] = [];
  const started = performance.now();
  const result = await a.withCheckpointHead(head => {
    // Queue the independent request at the final read. It must start after the
    // synchronous append and rollback, rather than block an awaiting holder.
    competing = Promise.resolve().then(async () => {
      order.push("writer");
      return await b.commitAuthority({expected_provider_revision: head.provider_revision,
        operation_id: "peer", next_projection: {value: 2}, events: [], receipts: []});
    });
    writeFileSync(join(directory, "checkpoint.json"), JSON.stringify(head));
    order.push("saved");
    return {ok: true};
  });
  const [updated, independent] = await Promise.all([competing,
    other.commitAuthority({expected_provider_revision: null, operation_id: "other",
      next_projection: {value: 3}, events: [], receipts: []})]);
  assert.equal(result.ok, true);
  assert.equal((updated as {status: string}).status, "applied");
  assert.equal(independent.status, "applied");
  assert.deepEqual(order, ["saved", "writer"]);
  assert.equal(JSON.parse(readFileSync(join(directory, "checkpoint.json"), "utf8")).head.value, 1);
  assert.ok(performance.now() - started < 4000, "must not incur the SQLite 5000ms busy timeout");
});
