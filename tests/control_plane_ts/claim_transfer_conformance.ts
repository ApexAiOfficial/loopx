/** Claimed work and its execution generation must move in one authority commit. */
import assert from "node:assert/strict";
import test from "node:test";
import type {AuthorityStoreConformanceFactory} from "./authority_store_conformance.ts";
import type {AuthorityStore} from "../../loopx/control_plane/coordination/authority_store.ts";
import type {JsonObject} from "../../loopx/control_plane/effect_program.ts";
import {executeCanonicalTaskLeaseLifecycle as execute,
  type CanonicalTaskLeaseLifecycleInput} from "../../loopx/control_plane/coordination/task_lease_lifecycle.ts";
import {executeCoordinationTodoUpdate} from "../../loopx/control_plane/coordination/todo_update.ts";
import {prepareCoordinationProjectionCommit} from "../../loopx/control_plane/coordination/coordination_projection.ts";
import {buildContinuationNote, computeContinuationTodoFacts, validateContinuationNote} from "../../loopx/control_plane/coordination/continuation_note.ts";
import {productionScaleClaimTransferFixture} from "./production_scale_coordination_fixture.ts";
import {authorityProjectionFixture} from "./authority_projection_fixture.ts";

async function loaded(store: AuthorityStore) {
  const head = await store.loadAuthority();
  assert.equal(head.status, "loaded");
  if (head.status !== "loaded") throw new Error("missing authority");
  return head;
}

export function registerClaimTransferConformance(provider: string, factory: AuthorityStoreConformanceFactory) {
  async function setup(t: test.TestContext, schema: "native" | "legacy" = "native",
    patch: {todo?: JsonObject; lease?: JsonObject; mode?: string} = {}) {
    const {store, contender} = await factory(t);
    const fixture = productionScaleClaimTransferFixture("goal-a", schema);
    const todos = fixture.projection.todos as JsonObject[], leases = fixture.projection.leases as JsonObject[];
    const todo = todos.find(row => row.todo_id === fixture.target)!;
    Object.assign(todo, patch.todo);
    todo.note = JSON.stringify(buildContinuationNote({work_summary: "Preserve the tested decision and continue the same work"},
      "source-session", computeContinuationTodoFacts(todo)));
    Object.assign(leases.find(row => row.todo_id === fixture.target)!, patch.lease);
    const seed = authorityProjectionFixture("goal-a", todos, leases, schema, {handoff_mode: patch.mode ?? "hard_lease"});
    assert.equal((await store.commitAuthority({operation_id: "seed-transfer", expected_provider_revision: null,
      next_projection: seed, events: [], receipts: []})).status, "applied");
    const request: CanonicalTaskLeaseLifecycleInput = {operation: "transfer", goal_id: "goal-a", todo_id: fixture.target,
      owner: "agent-a", idempotency_key: "lifecycle-a", expected_version: 3,
      new_owner: "agent-b", new_idempotency_key: "lifecycle-b", ttl_seconds: 600,
      transfer_claim: true, registered_agents: fixture.registered_agents, now: new Date(fixture.scenario.now)};
    return {store, contender, seed, request};
  }

  for (const schema of ["native", "legacy"] as const) {
    test(`${provider} ${schema} atomic claimed lease transfer preserves current context and the complete work graph`, async t => {
      const {store, contender, seed, request} = await setup(t, schema);
      const result = await execute(store, request);
      assert.equal(result.status, "applied", JSON.stringify(result));
      assert.equal(result.todo_changed, true);
      const head = await loaded(contender);
      assert.equal(head.cursor, "2");
      const current = (head.head.todos as JsonObject[]).find(row => row.todo_id === request.todo_id)!;
      const original = (seed.todos as JsonObject[]).find(row => row.todo_id === request.todo_id)!;
      assert.equal(validateContinuationNote(current.note, computeContinuationTodoFacts(current)).valid, true);
      assert.deepEqual(JSON.parse(String(current.note)), {...JSON.parse(String(original.note)),
        todo_facts: computeContinuationTodoFacts({...original, claimed_by: "agent-b"})});
      assert.deepEqual(current, {...original, note: current.note, claimed_by: "agent-b", last_actor_agent_id: "agent-a", updated_at: "2026-09-13T10:05:00Z"});
      const originalLease = (seed.leases as JsonObject[]).find(row => row.todo_id === request.todo_id)!;
      assert.deepEqual(result.lease, {...originalLease, owner: "agent-b", idempotency_key: "lifecycle-b",
        version: 4, lease_epoch: 8, updated_at: "2026-09-13T10:05:00Z", expires_at: "2026-09-13T10:15:00Z"});
      for (const partition of ["todos", "leases"]) assert.deepEqual(
        (head.head[partition] as JsonObject[]).filter(row => row.todo_id !== request.todo_id),
        (seed[partition] as JsonObject[]).filter(row => row.todo_id !== request.todo_id));
      const update = {goal_id: "goal-a", todo_id: request.todo_id, expected_role: "agent", actor_agent_id: "agent-a",
        registered_agents: request.registered_agents, operation_id: "old-owner-edit", patch: {note: "Continue the same work"},
        clear_fields: [], lease_idempotency_key: "lifecycle-a", lease_expected_version: 3, dry_run: false, now: request.now};
      assert.equal((await executeCoordinationTodoUpdate(store, update)).reason_code, "update_owner_mismatch");
      assert.deepEqual(await loaded(store), head);
      assert.equal((await executeCoordinationTodoUpdate(store, {...update, actor_agent_id: "agent-b",
        operation_id: "recipient-edit", lease_idempotency_key: "lifecycle-b", lease_expected_version: 4})).status, "applied");
      const back = await execute(contender, {...request, owner: "agent-b", idempotency_key: "lifecycle-b",
        expected_version: 4, new_owner: "agent-a", new_idempotency_key: "lifecycle-return"});
      assert.equal(back.status, "applied");
      const final = await loaded(store);
      const replay = await execute(contender, {...request, registered_agents: [], now: new Date("2030-01-01Z")});
      assert.equal(replay.status, "replayed");
      assert.equal(replay.changed, false);
      assert.equal(replay.claimed_by, "agent-b");
      assert.deepEqual(replay.original_receipt, result.original_receipt);
      assert.deepEqual(replay.lease, result.lease);
      assert.deepEqual(await loaded(store), final);
      for (const change of [{transfer_claim: false}, {new_idempotency_key: "retargeted"}, {ttl_seconds: 900}]) {
        assert.equal((await execute(store, {...request, ...change})).reason_code, "coordination_operation_identity_mismatch");
      }
      assert.deepEqual(await loaded(store), final);
    });
  }

  const targetCases: [string, {todo?: JsonObject; lease?: JsonObject; mode?: string}, string][] = [
    ["unclaimed", {todo: {claimed_by: null}}, "claim_transfer_owner_mismatch"],
    ["foreign claim", {todo: {claimed_by: "agent-b"}}, "claim_transfer_owner_mismatch"],
    ["source excluded", {todo: {excluded_agents: ["agent-a"]}}, "actor_excluded"],
    ["receiver excluded", {todo: {excluded_agents: ["agent-b"]}}, "actor_excluded"],
    ["source binding", {todo: {bound_agent: "agent-b"}}, "bound_agent_mismatch"],
    ["receiver binding", {todo: {bound_agent: "agent-a"}}, "bound_agent_mismatch"],
    ["done", {todo: {status: "done", done: true}}, "claim_transfer_requires_open_agent_todo"],
    ["archived", {todo: {archive_state: "archive"}}, "claim_transfer_requires_open_agent_todo"],
    ["released", {lease: {status: "released"}}, "lease_not_active"],
    ["foreign lease", {lease: {owner: "agent-b"}}, "lease_cas_mismatch"],
    ["exhausted epoch", {lease: {lease_epoch: Number.MAX_SAFE_INTEGER}}, "lease_generation_exhausted"],
    ["soft mode", {mode: "soft_claim"}, "claim_transfer_requires_hard_lease"],
  ];
  for (const [label, patch, code] of targetCases) {
    test(`${provider} claim transfer rejects ${label} without either half or a receipt`, async t => {
      const {store, request} = await setup(t, "native", patch);
      const before = await loaded(store);
      assert.equal((await execute(store, request)).reason_code, code);
      assert.deepEqual(await loaded(store), before);
    });
  }
  test(`${provider} claim transfer requires explicit intent and exact live execution proof`, async t => {
    const {store, request} = await setup(t);
    const before = await loaded(store);
    for (const [patch, code] of [
      [{transfer_claim: false}, "owner_conflicts_with_claim"],
      [{expected_version: 2}, "version_mismatch"],
      [{idempotency_key: "wrong-key"}, "lease_cas_mismatch"],
      [{new_idempotency_key: "lifecycle-a"}, "idempotency_key_reuse"],
      [{new_owner: "unknown"}, "actor_not_registered"],
      [{now: new Date("2028-01-01Z")}, "lease_not_active"],
      [{operation: "renew"}, "invalid_canonical_lifecycle_request"],
    ] as const) {
      assert.equal((await execute(store, {...request, ...patch})).reason_code, code);
      assert.deepEqual(await loaded(store), before);
    }
  });

  test(`${provider} claim transfer lost acknowledgement and CAS conflict recover without split ownership`, async t => {
    const {store, contender, request} = await setup(t);
    const losing = await execute(store, request, async () => {
      const current = await loaded(contender);
      const todo = (current.head.todos as JsonObject[]).find(row => row.todo_id === request.todo_id)!;
      assert.equal((await contender.commitAuthority(prepareCoordinationProjectionCommit({goal_id: "goal-a", operation_id: "competing-edit",
        expected_provider_revision: current.provider_revision, projection: current.head,
        mutations: [{kind: "todo_upsert", todo: {...todo, note: "Concurrent source decision"}}]}))).status, "applied");
    });
    assert.equal(losing.status, "conflict");
    const afterConflict = await loaded(store);
    assert.equal((afterConflict.head.todos as JsonObject[]).find(row => row.todo_id === request.todo_id)!.claimed_by, "agent-a");
    assert.equal((afterConflict.head.leases as JsonObject[]).find(row => row.todo_id === request.todo_id)!.owner, "agent-a");
    const uncertain: AuthorityStore = {storeIdentity: () => store.storeIdentity(), loadAuthority: () => store.loadAuthority(),
      readReceipt: id => store.readReceipt(id), scanCommitted: (...args) => store.scanCommitted(...args),
      commitAuthority: async commit => {
        assert.equal((await store.commitAuthority(commit)).status, "applied");
        throw new Error("lost acknowledgement");
      }};
    const recovered = await execute(uncertain, request);
    assert.equal(recovered.status, "recovered");
    const after = await loaded(contender);
    assert.equal(after.cursor, "3");
    assert.equal((after.head.todos as JsonObject[]).find(row => row.todo_id === request.todo_id)!.note, "Concurrent source decision");
    assert.equal((await execute(contender, request)).status, "replayed");
    assert.deepEqual(await loaded(store), after);
  });
  test(`${provider} same owner handover advances execution without fabricating a claim edit`, async t => {
    const {store, request, seed} = await setup(t);
    const result = await execute(store, {...request, new_owner: "agent-a"});
    assert.equal(result.status, "applied"); assert.equal(result.todo_changed, false);
    assert.equal((result.lease as JsonObject).lease_epoch, 8);
    assert.deepEqual((await loaded(store)).head.todos, seed.todos);
  });
}
