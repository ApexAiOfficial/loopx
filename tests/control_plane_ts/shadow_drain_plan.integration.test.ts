/** The planner must obtain proof from the real File store, not caller assertions. */
import assert from "node:assert/strict";
import test from "node:test";
import {readFile, readdir} from "node:fs/promises";
import {join} from "node:path";
import type {JsonObject} from "../../loopx/control_plane/effect_program.ts";
import {commitLocalAuthorityShadowEntry} from "../../loopx/control_plane/coordination/local_authority_shadow.ts";
import {readShadowDrainPlan, SHADOW_DRAIN_PLAN_REQUEST_SCHEMA} from "../../loopx/control_plane/coordination/shadow_drain_plan.ts";
import {requireShadowCaptureBinding} from "../../loopx/control_plane/coordination/shadow_management.ts";
import {fixture, pendingEntry, settleFiles, todo, type ShadowFixture} from "./shadow_file_fixture.ts";
import {productionScaleCoordinationFixture} from "./production_scale_coordination_fixture.ts";

async function request(f: ShadowFixture, entries: JsonObject[] = []): Promise<JsonObject> {
  const binding = await requireShadowCaptureBinding(f.root, "goal-a");
  return {schema_version: SHADOW_DRAIN_PLAN_REQUEST_SCHEMA, runtime_root: f.root, goal_id: "goal-a",
    partition: "todos", capture_lineage_id: binding.capture_lineage_id, store_identity: binding.store_identity,
    source_root_digest: binding.source_root_digest, cursor: null, entries, remaining_entries: 1,
    budget_open: true, acknowledgement: null};
}
function observed(commit: JsonObject): JsonObject {
  const entry = commit.entry as JsonObject;
  return {entry_id: entry.entry_id, seq: entry.seq, prepared: true, capture_lineage_id: entry.capture_lineage_id,
    prepared_sha256: entry.prepared_sha256, committed_sha256: entry.committed_sha256};
}
async function inventory(directory: string): Promise<Record<string, string>> {
  const entries: Record<string, string> = {};
  for (const name of (await readdir(directory)).sort()) entries[name] = await readFile(join(directory, name), "utf8");
  return entries;
}

for (const shape of ["native", "legacy"] as const) {
  test(`full retained ${shape} population survives recovery with bounded transport`, async t => {
    const f = await fixture(t);
    const complex = productionScaleCoordinationFixture("goal-a", shape);
    const todos = complex.projection.todos as JsonObject[];
    // Exercise the production projection validator, including archived dependencies,
    // standing decisions and unknown metadata, through a real outbox transaction.
    const first = await pendingEntry(f, 1, {handoff_mode: "hard_lease", todos});
    const firstResult = await commitLocalAuthorityShadowEntry(first);
    assert.equal(firstResult.outcome, "delivered", JSON.stringify(firstResult));
    await settleFiles(f, first, firstResult);
    const changed = structuredClone(todos);
    changed[0].note = "A second durable write whose ACK was lost";
    const second = await pendingEntry(f, 2, {handoff_mode: "hard_lease", todos: changed});
    const secondResult = await commitLocalAuthorityShadowEntry(second);
    assert.equal(secondResult.outcome, "delivered", JSON.stringify(secondResult));
    const directory = join(f.root, "authority-shadow", "outbox", "goal-a", "todos");
    const before = await inventory(directory);
    const input = await request(f, [observed(second)]);
    input.cursor = JSON.parse(before["drain-cursor.json"]);
    const plan = await readShadowDrainPlan(input);
    assert.equal(plan.status, "planned", JSON.stringify(plan));
    assert.deepEqual(plan.reclaim_entry_ids, [(second.entry as JsonObject).entry_id]);
    assert.equal((plan.cursor_update as JsonObject).last_seq, 2);
    assert.equal(plan.next_seq, 3);
    assert.ok(Buffer.byteLength(JSON.stringify(plan)) < 4096);
    assert.deepEqual(await inventory(directory), before, "planning never mutates the outbox");
    const loaded = await f.store.loadAuthority();
    assert.equal(loaded.status, "loaded");
    if (loaded.status !== "loaded") throw new Error("missing durable store");
    assert.deepEqual(loaded.head.todos, changed);
    assert.equal(changed.length, complex.expected_initial_todo_count);
    // A changed tail must block even when no recovery budget remains.
    input.entries = [{...observed(second), prepared_sha256: `sha256:${"f".repeat(64)}`}];
    input.remaining_entries = 0;
    const rejected = await readShadowDrainPlan(input);
    assert.equal(rejected.reason_code, "outbox_receipt_mismatch");
    assert.equal((rejected.view as JsonObject).provider_revision, secondResult.provider_revision);
    assert.deepEqual(await inventory(directory), before);
  });
}

test("provider history corruption cannot be replaced with caller-supplied proof", async t => {
  const f = await fixture(t);
  const commit = await pendingEntry(f, 1, {handoff_mode: "hard_lease", todos: [todo()]});
  const result = await commitLocalAuthorityShadowEntry(commit);
  assert.equal(result.outcome, "delivered");
  const input = await request(f, [observed(commit)]);
  const current = await f.store.loadAuthority();
  assert.equal(current.status, "loaded");
  if (current.status !== "loaded") throw new Error("missing durable store");
  // This is a valid generic provider commit but not a valid shadow transaction.
  const poison = await f.store.commitAuthority({expected_provider_revision: current.provider_revision,
    operation_id: "unproved-shadow-write", next_projection: current.head, events: [], receipts: []});
  assert.equal(poison.status, "applied");
  const failed = await readShadowDrainPlan(input);
  assert.equal(failed.status, "failed");
  assert.equal(failed.view, null, "unproved history cannot advertise verified readback");
  input.proof = {status: "trusted"};
  assert.equal((await readShadowDrainPlan(input)).reason_code, "shadow_drain_request_invalid");
});

test("native ACK readback preserves diagnostics but rejects mismatching receipt", async t => {
  const f = await fixture(t);
  const commit = await pendingEntry(f, 1, {handoff_mode: "hard_lease", todos: [todo()]});
  const result = await commitLocalAuthorityShadowEntry(commit);
  assert.equal(result.outcome, "delivered");
  const input = await request(f, [observed(commit)]);
  input.acknowledgement = {entry_id: (commit.entry as JsonObject).entry_id, seq: 1,
    cursor: result.cursor, provider_revision: result.provider_revision, store_identity: result.store_identity,
    partition_digest: commit.partition_digest, no_op: true};
  const failed = await readShadowDrainPlan(input);
  assert.equal(failed.reason_code, "shadow_commit_entry_result_invalid");
  assert.equal((failed.view as JsonObject).cursor, result.cursor);
  const directory = join(f.root, "authority-shadow", "outbox", "goal-a", "todos");
  assert.equal((await readdir(directory)).length, 2);
});

test("malformed checkpoint is rejected before attempting provider construction", async t => {
  const f = await fixture(t);
  const input = await request(f);
  input.cursor = {last_seq: true};
  let opened = false;
  const failed = await readShadowDrainPlan(input, {openStore: () => {opened = true; return f.store;}});
  assert.equal(failed.reason_code, "outbox_file_invalid");
  assert.equal(opened, false);
  assert.equal(failed.view, null);
});

test("bootstrap-only history never invents an applied partition checkpoint", async t => {
  const f = await fixture(t);
  const input = await request(f);
  const plan = await readShadowDrainPlan(input);
  assert.equal(plan.status, "planned");
  assert.equal(plan.history_present, false);
  assert.equal(plan.next_seq, 1);
  assert.equal(plan.cursor_update, null);
});
