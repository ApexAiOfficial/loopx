import assert from "node:assert/strict";
import {mkdtemp, rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import test from "node:test";

import type {
  NoKVBlobCasRequest,
  NoKVBlobCasResult,
  NoKVBlobReadResult,
  NoKVBlobTransport,
  NoKVStoreIdentityResult,
} from "../../loopx/control_plane/coordination/nokv_authority_store.ts";
import {NoKVAuthorityStore} from "../../loopx/control_plane/coordination/nokv_authority_store.ts";
import {FileAuthorityStore} from "../../loopx/control_plane/coordination/file_authority_store.ts";
import {SqliteAuthorityStore} from "../../loopx/control_plane/coordination/sqlite_authority_store.ts";
import type {AuthorityStore} from "../../loopx/control_plane/coordination/authority_store.ts";
import type {AuthorityStoreScanResult} from "../../loopx/control_plane/coordination/authority_store.ts";
import {canonicalAuthoritySha256} from "../../loopx/control_plane/coordination/authority_store_codec.ts";
import {prepareCoordinationProjectionCommit} from "../../loopx/control_plane/coordination/coordination_projection.ts";
import {PRODUCTION_SCALE_HISTORY, productionScaleCoordinationFixture,
  productionScaleHistoryProjection, productionScaleObservationStep} from
  "./production_scale_coordination_fixture.ts";
import type {AuthorityProjectionSchema} from "./authority_projection_fixture.ts";

interface BlobState {
  identity: string;
  generation: number;
  bytes: Uint8Array | null;
}

class MemoryNoKVTransport implements NoKVBlobTransport {
  private readonly state: BlobState;
  constructor(state: BlobState) { this.state = state; }
  async storeIdentity(_workbench: string): Promise<NoKVStoreIdentityResult> {
    return {status: "available", store_identity: this.state.identity};
  }
  async readBlob(_workbench: string, _path: string): Promise<NoKVBlobReadResult> {
    return this.state.bytes === null
      ? {status: "missing"}
      : {status: "loaded", bytes: this.state.bytes.slice(), generation: this.state.generation};
  }
  async casPublishBlob(request: NoKVBlobCasRequest): Promise<NoKVBlobCasResult> {
    if ((this.state.bytes === null ? null : this.state.generation) !== request.expected_generation) {
      return {status: "conflict", current_generation: this.state.bytes === null ? null : this.state.generation};
    }
    this.state.generation += 1;
    this.state.bytes = request.bytes.slice();
    return {status: "applied", generation: this.state.generation};
  }
}

interface ProviderFixture {
  readonly name: string;
  readonly store: AuthorityStore;
  readonly contender: AuthorityStore;
  readonly close: () => Promise<void>;
}

async function providers(t: test.TestContext): Promise<ProviderFixture[]> {
  const fileRoot = await mkdtemp(join(tmpdir(), "authority-parity-file-"));
  const sqliteRoot = await mkdtemp(join(tmpdir(), "authority-parity-sqlite-"));
  t.after(async () => {
    await Promise.all([rm(fileRoot, {recursive: true, force: true}), rm(sqliteRoot, {recursive: true, force: true})]);
  });
  const file = new FileAuthorityStore(fileRoot, "parity-goal");
  const sqlite = new SqliteAuthorityStore(sqliteRoot, "parity-goal");
  const state: BlobState = {identity: `nokv:parity-workbench:${"b".repeat(32)}`, generation: 0, bytes: null};
  const nokvTransport = new MemoryNoKVTransport(state);
  const nokv = new NoKVAuthorityStore(nokvTransport, {
    tenant_id: "parity-tenant", goal_id: "parity-goal", workbench: "parity-workbench",
  });
  return [
    {name: "file", store: file, contender: new FileAuthorityStore(fileRoot, "parity-goal"), close: async () => {}},
    {name: "sqlite", store: sqlite, contender: new SqliteAuthorityStore(sqliteRoot, "parity-goal"), close: async () => {}},
    {name: "nokv", store: nokv, contender: new NoKVAuthorityStore(nokvTransport, {
      tenant_id: "parity-tenant", goal_id: "parity-goal", workbench: "parity-workbench",
    }), close: async () => {}},
  ];
}

async function logicalTrace(store: AuthorityStore, schema: AuthorityProjectionSchema): Promise<string[]> {
  const fixture = productionScaleCoordinationFixture("parity-goal", schema);
  const seeded = await store.commitAuthority({
    operation_id: "parity-seed", expected_provider_revision: null,
    events: [], receipts: [], next_projection: fixture.projection,
  });
  assert.equal(seeded.status, "applied", JSON.stringify(seeded));
  const loaded = await store.loadAuthority();
  assert.equal(loaded.status, "loaded");
  if (loaded.status !== "loaded") throw new Error("parity seed did not load");
  const monitor = (loaded.head.todos as Record<string, unknown>[]).find(todo =>
    todo.task_class === "continuous_monitor" && !(loaded.head.leases as Record<string, unknown>[])
      .some(lease => lease.todo_id === todo.todo_id));
  if (!monitor) throw new Error("parity fixture needs a lease-free monitor");
  const changed = {...monitor, reason: "parity observation", last_actor_agent_id: "agent-a"};
  const first = await store.commitAuthority(prepareCoordinationProjectionCommit({
    goal_id: "parity-goal", operation_id: "parity-observation",
    expected_provider_revision: loaded.provider_revision, projection: loaded.head,
    mutations: [{kind: "todo_upsert", todo: changed}],
  }));
  assert.equal(first.status, "applied", JSON.stringify(first));
  const afterObservation = await store.loadAuthority();
  assert.equal(afterObservation.status, "loaded");
  if (afterObservation.status !== "loaded") throw new Error("parity observation did not load");
  const lease = {todo_id: monitor.todo_id, owner: "agent-a", status: "active",
    idempotency_key: "parity-lease", version: 1, lease_epoch: 1,
    expires_at: "2099-01-01T00:00:00Z"};
  const second = await store.commitAuthority(prepareCoordinationProjectionCommit({
    goal_id: "parity-goal", operation_id: "parity-lease",
    expected_provider_revision: afterObservation.provider_revision, projection: afterObservation.head,
    mutations: [{kind: "lease_upsert", lease}],
  }));
  assert.equal(second.status, "applied", JSON.stringify(second));
  const final = await store.loadAuthority();
  assert.equal(final.status, "loaded");
  if (final.status !== "loaded") throw new Error("parity final head did not load");
  const page = await store.scanCommitted(null, 10);
  assert.equal(page.status, "page");
  if (page.status !== "page") throw new Error("parity scan did not return a page");
  assert.equal(page.transactions.length, 3);
  assert.equal((await store.readReceipt("parity-observation")).status, "found");
  assert.equal((await store.readReceipt("parity-lease")).status, "found");
  return [
    canonicalAuthoritySha256(final.head),
    ...page.transactions.map(transaction => canonicalAuthoritySha256({
      operation_id: transaction.operation_id,
      events: transaction.events,
      projection: transaction.projection,
      receipts: transaction.receipts,
    })),
  ];
}

for (const schema of ["legacy", "native"] as const) {
  test(`provider parity preserves one logical transaction trace (${schema})`, async t => {
    const traces = await Promise.all((await providers(t)).map(async provider => ({
      name: provider.name,
      trace: await logicalTrace(provider.store, schema),
    })));
    assert.ok(traces.length > 0);
    assert.deepEqual(
      traces.map(item => item.trace),
      traces.map(() => traces[0]!.trace),
    );
  });
}

/**
 * The same retained history through every local provider.
 *
 * Each step is one domain observation over the production-scale projection, so
 * the comparison covers paged replay of many transactions rather than a single
 * seed. The prefix is bounded by the fixture because the journal providers
 * rewrite their complete retained document on every commit.
 */
async function historyTrace(store: AuthorityStore, schema: AuthorityProjectionSchema): Promise<string[]> {
  const fixture = productionScaleHistoryProjection("parity-goal", schema);
  const plan = PRODUCTION_SCALE_HISTORY;
  let projection = fixture.projection;
  let revision: string | null = null;
  const seeded = await store.commitAuthority({operation_id: "history-seed", expected_provider_revision: null,
    events: [], receipts: [], next_projection: projection});
  assert.equal(seeded.status, "applied", JSON.stringify(seeded));
  if (seeded.status !== "applied") throw new Error("history seed did not apply");
  revision = seeded.provider_revision;
  for (let index = 0; index < plan.parity_commit_count; index += 1) {
    const step = productionScaleObservationStep(projection, index);
    const prepared = prepareCoordinationProjectionCommit({
      goal_id: "parity-goal", operation_id: step.operation_id,
      expected_provider_revision: revision, projection, mutations: [step.mutation],
    });
    const applied = await store.commitAuthority(prepared);
    assert.equal(applied.status, "applied", JSON.stringify(applied));
    if (applied.status !== "applied") throw new Error("history observation did not apply");
    revision = applied.provider_revision;
    projection = prepared.next_projection;
  }
  const trace: string[] = [canonicalAuthoritySha256(projection)];
  let page: AuthorityStoreScanResult = await store.scanCommitted(null, plan.scan_page_size);
  let pages = 0;
  while (page.status === "page" && page.transactions.length > 0) {
    pages += 1;
    for (const transaction of page.transactions) {
      trace.push(canonicalAuthoritySha256({operation_id: transaction.operation_id,
        events: transaction.events, projection: transaction.projection, receipts: transaction.receipts}));
    }
    const last = page.transactions[page.transactions.length - 1]!;
    page = await store.scanCommitted(last.cursor, plan.scan_page_size);
  }
  assert.equal(page.status, "page", JSON.stringify(page));
  assert.equal(trace.length - 1, plan.parity_commit_count + 1);
  assert.equal(pages, Math.ceil((plan.parity_commit_count + 1) / plan.scan_page_size));
  return trace;
}

for (const schema of ["legacy", "native"] as const) {
  test(`provider parity preserves one long retained history (${schema})`, {timeout: 120000}, async t => {
    const traces = await Promise.all((await providers(t)).map(async provider => ({
      name: provider.name,
      trace: await historyTrace(provider.store, schema),
    })));
    assert.deepEqual(traces.map(item => item.trace), traces.map(() => traces[0]!.trace));
  });
}
