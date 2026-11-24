import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import test from "node:test";
import type {JsonObject} from "../../loopx/control_plane/effect_program.ts";
import {
  planShadowDrain, SHADOW_DRAIN_PLAN_REQUEST_SCHEMA,
} from "../../loopx/control_plane/coordination/shadow_drain_plan.ts";

const digest = `sha256:${"a".repeat(64)}`;
const otherDigest = `sha256:${"b".repeat(64)}`;
function id(seq: number, partition = "todos"): string {
  return `local-shadow-tx-${createHash("sha256").update(`${partition}:${seq}`).digest("hex")}`;
}
function transaction(seq: number, partition = "todos", noOp = false): JsonObject {
  return {
    operation_id: id(seq, partition), cursor: String(seq + 1), provider_revision: `revision-${seq + 1}`,
    projection_partitions: {todos: {partition_digest: digest}, leases: null},
    receipts: [{entry_id: id(seq, partition), seq, partition,
      capture_lineage_id: "lineage-a", source_root_digest: digest,
      prepared_sha256: digest, committed_sha256: noOp ? null : otherDigest,
      resolution: noOp ? "abandoned" : "committed", no_op: noOp,
      partition_digest: noOp ? null : digest}],
  };
}
function observation(seq: number): JsonObject {
  return {entry_id: id(seq), seq, prepared: true, capture_lineage_id: "lineage-a",
    prepared_sha256: digest, committed_sha256: otherDigest};
}
function fixture(count = 2): {request: JsonObject; view: JsonObject; transactions: JsonObject[]} {
  const transactions = [{operation_id: "bootstrap", cursor: "1", provider_revision: "revision-1", receipts: []},
    ...Array.from({length: count}, (_, i) => transaction(i + 1))];
  const tail = transactions.at(-1)!;
  return {
    request: {schema_version: SHADOW_DRAIN_PLAN_REQUEST_SCHEMA, runtime_root: "/disposable", goal_id: "goal-a",
      partition: "todos", capture_lineage_id: "lineage-a", store_identity: "file:fixture",
      source_root_digest: digest, cursor: null, entries: [observation(1), observation(2), observation(3)],
      remaining_entries: 20, budget_open: true, acknowledgement: null},
    view: {status: "loaded", store_identity: "file:fixture", cursor: tail.cursor,
      provider_revision: tail.provider_revision, head_digest: digest,
      proof: {capture_lineage_id: "lineage-a", transactions}},
    transactions,
  };
}
function cursor(): JsonObject {
  return {schema_version: "loopx_local_authority_shadow_drain_cursor_v0", partition: "todos", last_seq: 1,
    last_entry_id: id(1), last_partition_digest: digest, last_cursor: "2",
    last_provider_revision: "revision-2", updated_at: "2026-09-01T00:00:00Z"};
}
function ack(): JsonObject {
  return {entry_id: id(2), seq: 2, cursor: "3", provider_revision: "revision-3",
    store_identity: "file:fixture", no_op: false, partition_digest: digest};
}
function rejected(request: JsonObject, view: JsonObject, code: string): void {
  assert.throws(() => planShadowDrain(request, view), (error: unknown) =>
    error instanceof Error && "reasonCode" in error && error.reasonCode === code);
}

test("recovery separates proved residue, pending work and checkpoint effects", () => {
  const {request, view} = fixture();
  const result = planShadowDrain(request, view);
  assert.deepEqual(result.reclaim_entry_ids, [id(1), id(2)]);
  assert.deepEqual(result.pending_entry_ids, [id(3)]);
  assert.equal(result.next_seq, 3);
  assert.deepEqual(result.cursor_update, {last_seq: 2, last_entry_id: id(2), last_partition_digest: digest,
    last_cursor: "3", last_provider_revision: "revision-3"});
  assert.deepEqual((result.replay_entries as JsonObject[]).map(e => [e.seq, e.outcome, e.no_op]),
    [[1, "replayed", false], [2, "replayed", false]]);
  assert.equal("transactions" in result, false);
});

test("acknowledged entry is reclaimed without counting a second replay", () => {
  const {request, view} = fixture();
  request.acknowledgement = ack();
  request.remaining_entries = 1;
  const result = planShadowDrain(request, view);
  assert.deepEqual(result.reclaim_entry_ids, [id(1), id(2)]);
  assert.deepEqual((result.replay_entries as JsonObject[]).map(e => e.entry_id), [id(1)]);
  assert.equal(result.budget_exhausted, false);
});

for (const remaining of [0, 1, 2]) {
  test(`budget ${remaining} limits reclamation while checkpoint reaches proved history`, () => {
    const {request, view} = fixture();
    request.remaining_entries = remaining;
    const result = planShadowDrain(request, view);
    assert.equal((result.reclaim_entry_ids as unknown[]).length, remaining);
    assert.equal((result.cursor_update as JsonObject).last_seq, 2);
    assert.equal(result.budget_exhausted, remaining < 2);
  });
}

test("expired budget yields no effects, even for an acknowledged commit", () => {
  const {request, view} = fixture();
  request.budget_open = false;
  request.acknowledgement = ack();
  const result = planShadowDrain(request, view);
  for (const key of ["reclaim_entry_ids", "pending_entry_ids", "replay_entries"]) assert.deepEqual(result[key], []);
  assert.equal(result.cursor_update, null);
  assert.equal(result.budget_exhausted, true);
});

for (const budgetOpen of [false, true]) {
  test(`corrupt tail is rejected before budget selection (open=${budgetOpen})`, () => {
    const {request, view} = fixture();
    request.budget_open = budgetOpen;
    request.remaining_entries = 1;
    (request.entries as JsonObject[])[1].prepared_sha256 = otherDigest;
    rejected(request, view, "outbox_receipt_mismatch");
  });
}

for (const key of ["last_seq", "last_entry_id", "last_partition_digest", "last_cursor", "last_provider_revision"]) {
  test(`checkpoint requires exact ${key} history anchor`, () => {
    const {request, view} = fixture();
    request.cursor = {...cursor(), [key]: key === "last_seq" ? 4 : key === "last_partition_digest" ? otherDigest : key === "last_entry_id" ? id(99) : "foreign"};
    rejected(request, view, "outbox_cursor_unproved");
  });
}

test("an exact current checkpoint needs no rewrite", () => {
  const {request, view} = fixture(1);
  request.cursor = cursor();
  request.entries = [];
  assert.equal(planShadowDrain(request, view).cursor_update, null);
});

for (const key of ["entry_id", "seq", "cursor", "provider_revision", "store_identity", "no_op", "partition_digest"]) {
  test(`ACK ${key} is checked against the exact committed receipt`, () => {
    const {request, view} = fixture();
    request.acknowledgement = {...ack(), [key]: key === "seq" ? 1 : key === "no_op" ? true : "foreign"};
    rejected(request, view, "shadow_commit_entry_result_invalid");
  });
}

test("numeric-looking ACK strings cannot stand in for a sequence", () => {
  const {request, view} = fixture();
  request.acknowledgement = {...ack(), seq: "2"};
  rejected(request, view, "shadow_commit_entry_result_invalid");
});

for (const [name, mutate, code] of [
  ["foreign lineage", (r: JsonObject) => {r.capture_lineage_id = "old";}, "outbox_receipt_unproved"],
  ["foreign store", (r: JsonObject) => {r.store_identity = "other";}, "outbox_receipt_unproved"],
  ["foreign root", (r: JsonObject) => {r.source_root_digest = otherDigest;}, "outbox_receipt_unproved"],
  ["marker without receipt", (r: JsonObject) => {(r.entries as JsonObject[])[2].prepared = false;}, "outbox_file_invalid"],
  ["stale pending", (r: JsonObject) => {(r.entries as JsonObject[])[2].capture_lineage_id = "old";}, "stale_generation"],
  ["duplicate sequence", (r: JsonObject) => {(r.entries as JsonObject[])[1].seq = 1;}, "shadow_drain_request_invalid"],
  ["duplicate identity", (r: JsonObject) => {(r.entries as JsonObject[])[1].entry_id = id(1);}, "shadow_drain_request_invalid"],
  ["fractional sequence", (r: JsonObject) => {(r.entries as JsonObject[])[0].seq = 0.5;}, "shadow_drain_request_invalid"],
  ["boolean sequence", (r: JsonObject) => {(r.entries as JsonObject[])[0].seq = true;}, "shadow_drain_request_invalid"],
  ["unknown request field", (r: JsonObject) => {r.trust_history = true;}, "shadow_drain_request_invalid"],
] as const) {
  test(`reject ${name}`, () => {
    const {request, view} = fixture();
    mutate(request);
    rejected(request, view, code);
  });
}

test("marker-only residue can recover only with matching committed-byte proof", () => {
  const {request, view} = fixture();
  request.entries = [{...observation(2), prepared: false, prepared_sha256: null, capture_lineage_id: null}];
  assert.deepEqual(planShadowDrain(request, view).reclaim_entry_ids, [id(2)]);
  (request.entries as JsonObject[])[0].committed_sha256 = digest;
  rejected(request, view, "outbox_receipt_mismatch");
});

test("partition sequences remain independent of interleaved global cursors", () => {
  const {request, view, transactions} = fixture();
  transactions.splice(2, 0, {...transaction(1, "leases"), cursor: "3", provider_revision: "revision-3"});
  Object.assign(transactions[3], {cursor: "4", provider_revision: "revision-4"});
  Object.assign(view, {cursor: "4", provider_revision: "revision-4"});
  const result = planShadowDrain(request, view);
  assert.equal(result.next_seq, 3);
  assert.equal((result.cursor_update as JsonObject).last_cursor, "4");
});

for (const priorApplied of [false, true]) {
  test(`no-op advances position and preserves the applied marker (prior=${priorApplied})`, () => {
    const {request, view, transactions} = fixture(priorApplied ? 2 : 1);
    const seq = priorApplied ? 2 : 1;
    const tx = transaction(seq, "todos", true);
    tx.projection_partitions = {todos: priorApplied ? {partition_digest: digest} : null, leases: null};
    transactions[seq] = tx;
    request.entries = [{...observation(seq), committed_sha256: null}];
    const result = planShadowDrain(request, view);
    assert.equal(result.next_seq, seq + 1);
    assert.equal((result.cursor_update as JsonObject).last_partition_digest, priorApplied ? digest : null);
    assert.equal((result.replay_entries as JsonObject[])[0].partition_digest, null);
    assert.equal((result.replay_entries as JsonObject[])[0].no_op, true);
  });
}

for (const defect of ["missing-tail", "sequence-gap", "receipt-root", "operation-identity"]) {
  test(`refuse ${defect} in a claimed history proof`, () => {
    const {request, view, transactions} = fixture();
    if (defect === "missing-tail") transactions.pop();
    else if (defect === "sequence-gap") (transactions[2].receipts as JsonObject[])[0].seq = 3;
    else if (defect === "receipt-root") (transactions[2].receipts as JsonObject[])[0].source_root_digest = otherDigest;
    else transactions[2].operation_id = "unrelated";
    rejected(request, view, "outbox_receipt_unproved");
  });
}

test("history volume does not become RPC response volume when there is no residue", () => {
  const {request, view} = fixture(4000);
  request.entries = [];
  assert.ok(Buffer.byteLength(JSON.stringify(view)) > 2 * 1024 * 1024);
  const result = planShadowDrain(request, view);
  assert.ok(Buffer.byteLength(JSON.stringify(result)) < 2048);
  assert.equal(result.next_seq, 4001);
  assert.equal((result.cursor_update as JsonObject).last_seq, 4000);
  assert.deepEqual(result.replay_entries, []);
});
