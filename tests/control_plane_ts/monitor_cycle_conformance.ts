/** A new observation cycle retires execution; it never reuses its authority. */
import assert from "node:assert/strict";
import test from "node:test";
import type {JsonObject} from "../../loopx/control_plane/effect_program.ts";
import type {AuthorityStore, AuthorityStoreCommit} from "../../loopx/control_plane/coordination/authority_store.ts";
import {executeCoordinationTodoUpdate, type CoordinationTodoUpdateInput} from "../../loopx/control_plane/coordination/todo_update.ts";
import {executeCanonicalTaskLeaseAcquire} from "../../loopx/control_plane/coordination/task_lease_acquire.ts";
import {executeCanonicalTaskLeaseLifecycle} from "../../loopx/control_plane/coordination/task_lease_lifecycle.ts";
import {executeCoordinationMonitorPoll} from "../../loopx/control_plane/coordination/todo_monitor_poll.ts";
import {indexCoordinationProjection} from "../../loopx/control_plane/coordination/coordination_projection.ts";
import {productionScaleCompletedMonitorFixture, productionScaleLeasedMonitorFixture} from "./production_scale_coordination_fixture.ts";
import type {AuthorityStoreConformanceFactory} from "./authority_store_conformance.ts";

function input(f: ReturnType<typeof productionScaleCompletedMonitorFixture>): CoordinationTodoUpdateInput {
  return {goal_id: String(f.projection.goal_id), todo_id: f.target, expected_role: "agent",
    actor_agent_id: f.actor, registered_agents: f.registered_agents, operation_id: "next-cycle",
    patch: {}, clear_fields: [], planning_intent: {status: "open"}, dry_run: false, now: f.now,
    monitor_observation: {generated_at: f.now.toISOString(), result_hash: "previous-evidence",
      material_change: true, monitor_effect_id: "next-cycle", cadence: "1h"}};
}

async function seed(store: AuthorityStore, projection: JsonObject) {
  assert.equal((await store.commitAuthority({operation_id: "seed", expected_provider_revision: null,
    events: [], receipts: [], next_projection: projection})).status, "applied");
}

export function registerMonitorCycleConformance(provider: string, factory: AuthorityStoreConformanceFactory) {
  for (const schema of ["native", "legacy"] as const) for (const retained of ["released", "expired", "active"] as const) {
    test(`${provider}: Monitor cycle ${schema}/${retained} retires old execution and admits a fresh generation`, async t => {
      const {store, contender} = await factory(t);
      const f = productionScaleCompletedMonitorFixture("monitor-cycle", schema, retained);
      await seed(store, f.projection);
      const request = input(f);
      const priorLease = (f.projection.leases as JsonObject[]).find(row => row.todo_id === f.target)!;
      const before = await store.loadAuthority();
      const preview = await executeCoordinationTodoUpdate(store, {...request, dry_run: true});
      assert.equal(preview.status, "planned", JSON.stringify(preview));
      assert.deepEqual(await store.loadAuthority(), before);
      const result = await executeCoordinationTodoUpdate(store, request);
      assert.equal(result.status, "applied", JSON.stringify(result));
      const head = await store.loadAuthority(); assert.equal(head.status, "loaded");
      if (head.status !== "loaded") return;
      const index = indexCoordinationProjection(head.head, request.goal_id);
      const lease = index.leases.get(f.target)!;
      assert.equal(index.todos.get(f.target)!.status, "open");
      assert.equal(index.todos.get(f.target)!.material_change_generation, 5);
      assert.equal(lease.status, "released");
      assert.equal(lease.version, priorLease.version);
      assert.equal(lease.lease_epoch, priorLease.lease_epoch);
      if (retained === "released") assert.deepEqual(lease, priorLease, "historical release stays immutable");
      assert.deepEqual((head.head.leases as JsonObject[]).filter(row => row.todo_id !== f.target),
        (f.projection.leases as JsonObject[]).filter(row => row.todo_id !== f.target));
      const oldProof = {operation: "renew" as const, goal_id: request.goal_id, todo_id: f.target,
        owner: f.actor, idempotency_key: String(priorLease.idempotency_key), expected_version: Number(priorLease.version),
        ttl_seconds: 600, registered_agents: f.registered_agents, now: f.now};
      assert.equal((await executeCanonicalTaskLeaseLifecycle(store, oldProof)).status, "failed");
      const acquire = {goal_id: request.goal_id, todo_id: f.target, owner: f.actor,
        idempotency_key: "fresh-cycle-execution", expected_version: Number(lease.version),
        ttl_seconds: 600, write_scopes: [], registered_agents: f.registered_agents, now: f.now};
      const fresh = await executeCanonicalTaskLeaseAcquire(contender, acquire);
      assert.equal(fresh.status, "applied", JSON.stringify(fresh));
      const freshLease = fresh.lease as JsonObject;
      assert.equal(freshLease.version, Number(priorLease.version) + 1);
      assert.equal(freshLease.lease_epoch, Number(priorLease.lease_epoch) + 1);
      const acquired = await store.loadAuthority();
      const replay = await executeCoordinationTodoUpdate(store, request);
      assert.equal(replay.status, "replayed");
      assert.deepEqual(replay.monitor_lifecycle_transition, result.monitor_lifecycle_transition);
      assert.deepEqual(await store.loadAuthority(), acquired, "old observation replay must not retire fresh execution");
      const poll = await executeCoordinationTodoUpdate(store, {...request, operation_id: "fresh-poll",
        planning_intent: {}, lease_idempotency_key: acquire.idempotency_key,
        lease_expected_version: Number(freshLease.version),
        monitor_observation: {...request.monitor_observation!, generated_at: "2026-09-01T01:01:00Z",
          monitor_effect_id: "fresh-poll", result_hash: "next-evidence"}});
      assert.equal(poll.status, "applied", JSON.stringify(poll));
      assert.equal((poll.monitor_poll_transition as JsonObject).material_change_generation, 6);
    });
  }

  test(`${provider}: Monitor cycle rejects stale authority, bundled execution proof and old observations without retirement`, async t => {
    const {store} = await factory(t);
    const f = productionScaleCompletedMonitorFixture("monitor-cycle-denied", "native", "active");
    await seed(store, f.projection);
    const request = input(f), before = await store.loadAuthority();
    for (const extra of [
      {actor_agent_id: "agent-b"}, {registered_agents: []},
      {lease_expected_version: f.proof.expected_version}, {lease_idempotency_key: f.proof.idempotency_key},
      {lease_idempotency_key: f.proof.idempotency_key, lease_expected_version: f.proof.expected_version},
      {monitor_observation: {...request.monitor_observation!, material_change: false}},
      {monitor_observation: {...request.monitor_observation!, generated_at: "2026-09-01T00:30:00Z"}},
      {planning_intent: {status: "open", claimed_by: "agent-b"}},
    ]) {
      assert.equal((await executeCoordinationTodoUpdate(store, {...request, ...extra})).status, "failed", JSON.stringify(extra));
      assert.deepEqual(await store.loadAuthority(), before);
      assert.equal((await store.readReceipt(request.operation_id)).status, "missing");
    }
    let witnesses = 0;
    assert.equal((await executeCoordinationTodoUpdate(store, request, async () => ++witnesses === 1)).status, "failed");
    assert.deepEqual(await store.loadAuthority(), before);
    for (const [index, invalid] of [{goal_id: "other-goal"}, {version: "not-a-generation"},
      {owner: " padded "}, {status: "unknown"}].entries()) {
      const head = await store.loadAuthority(); assert.equal(head.status, "loaded");
      if (head.status !== "loaded") return;
      const leases = (f.projection.leases as JsonObject[]).map(row => row.todo_id === f.target ? {...row, ...invalid} : row);
      await store.commitAuthority({operation_id: `corrupt-history-${index}`, expected_provider_revision: head.provider_revision,
        next_projection: {...f.projection, leases}, events: [], receipts: []});
      const malformed = await store.loadAuthority();
      const result = await executeCoordinationTodoUpdate(store, request);
      assert.equal(result.reason_code, "invalid_coordination_projection");
      assert.deepEqual(await store.loadAuthority(), malformed);
    }
  });

  test(`${provider}: Monitor observation callers share actor and handoff admission`, async t => {
    const {store} = await factory(t);
    const f = productionScaleLeasedMonitorFixture("monitor-admission-parity");
    await seed(store, f.projection);
    const request = {...input(f), planning_intent: {}, lease_idempotency_key: f.proof.idempotency_key,
      lease_expected_version: f.proof.expected_version};
    for (const [i, extra] of [{actor_agent_id: "agent-b"}, {actor_agent_id: null}, {registered_agents: []},
      {lease_idempotency_key: "old-key"}, {lease_expected_version: 900}].entries()) {
      const candidate = {...request, ...extra, operation_id: `denied-${i}`};
      const before = await store.loadAuthority();
      const updated = await executeCoordinationTodoUpdate(store, candidate);
      const polled = await executeCoordinationMonitorPoll(store, {goal_id: request.goal_id, operation_id: candidate.operation_id,
        actor_agent_id: candidate.actor_agent_id, registered_agents: candidate.registered_agents,
        dry_run: false, now: f.now, observation: {todo_id: f.target, generated_at: f.now.toISOString(), result_hash: "new", material_change: true}, intent: {},
        lease_proof: {idempotency_key: candidate.lease_idempotency_key!, expected_version: candidate.lease_expected_version!}});
      assert.equal(updated.status, "failed"); assert.equal(polled.status, "failed");
      assert.deepEqual(await store.loadAuthority(), before);
    }
    const current = await store.loadAuthority(); assert.equal(current.status, "loaded");
    if (current.status !== "loaded") return;
    await store.commitAuthority({operation_id: "soft-claim-fixture", expected_provider_revision: current.provider_revision,
      next_projection: {...current.head, handoff_mode: "soft_claim"}, events: [], receipts: []});
    const before = await store.loadAuthority();
    const updated = await executeCoordinationTodoUpdate(store, request);
    const polled = await executeCoordinationMonitorPoll(store, {goal_id: request.goal_id, operation_id: "soft-poll",
      actor_agent_id: f.actor, registered_agents: f.registered_agents, dry_run: false, now: f.now,
      observation: {todo_id: f.target, generated_at: f.now.toISOString(), result_hash: "new", material_change: true},
      intent: {}, lease_proof: f.proof});
    assert.equal(updated.reason_code, "handoff_mode_forbids_lease");
    assert.equal(polled.status, "failed"); assert.match(String(polled.reason), /soft_claim/);
    assert.deepEqual(await store.loadAuthority(), before);
  });

  test(`${provider}: Monitor reactivation honors explicit handoff mode with or without retained history`, async t => {
    const {store} = await factory(t);
    const f = productionScaleCompletedMonitorFixture("monitor-cycle-mode", "native", "released");
    const request = input(f);
    for (const [index, mode] of ["soft_claim", "hard_lease"].entries()) {
      const prior = await store.loadAuthority();
      const projection = {...f.projection, handoff_mode: mode,
        leases: mode === "hard_lease" ? (f.projection.leases as JsonObject[]).filter(row => row.todo_id !== f.target) : f.projection.leases};
      await store.commitAuthority({operation_id: `seed-mode-${index}`,
        expected_provider_revision: prior.status === "loaded" ? prior.provider_revision : null,
        next_projection: projection, events: [], receipts: []});
      const result = await executeCoordinationTodoUpdate(store, {...request, operation_id: `reopen-${mode}`});
      assert.equal(result.status, "applied", JSON.stringify(result));
      assert.equal((result.monitor_lifecycle_transition as JsonObject).next_execution,
        mode === "soft_claim" ? "ordinary_admission" : "acquire_fresh_lease");
      const observed = await executeCoordinationTodoUpdate(store, {...request, operation_id: `poll-${mode}`,
        planning_intent: {}, monitor_observation: {...request.monitor_observation!,
          monitor_effect_id: `poll-${mode}`, generated_at: "2026-09-01T01:01:00Z", result_hash: "changed"}});
      assert.equal(observed.status, mode === "soft_claim" ? "applied" : "failed");
      const polled = await executeCoordinationMonitorPoll(store, {goal_id: request.goal_id, operation_id: `quota-poll-${mode}`,
        actor_agent_id: f.actor, registered_agents: f.registered_agents, dry_run: false, now: f.now,
        observation: {todo_id: f.target, generated_at: "2026-09-01T01:02:00Z", result_hash: "next", material_change: true}, intent: {}});
      assert.equal(polled.status, mode === "soft_claim" ? "applied" : "failed");
    }
  });

  test(`${provider}: Monitor cycle CAS and lost response keep retirement atomic`, async t => {
    const {store, contender} = await factory(t);
    const f = productionScaleCompletedMonitorFixture("monitor-cycle-recovery", "native", "active");
    await seed(store, f.projection);
    const request = input(f);
    const raced = new Proxy(store, {get(target, property) {
      if (property === "commitAuthority") return async (commit: AuthorityStoreCommit) => {
        const current = await contender.loadAuthority(); assert.equal(current.status, "loaded");
        if (current.status !== "loaded") throw new Error("missing head");
        await contender.commitAuthority({operation_id: "competing-write", expected_provider_revision: current.provider_revision,
          next_projection: current.head, events: [], receipts: []});
        return target.commitAuthority(commit);
      };
      const value = Reflect.get(target, property); return typeof value === "function" ? value.bind(target) : value;
    }});
    assert.equal((await executeCoordinationTodoUpdate(raced, request)).status, "conflict");
    const unchanged = await store.loadAuthority(); assert.equal(unchanged.status, "loaded");
    if (unchanged.status === "loaded") assert.deepEqual(unchanged.head, f.projection);
    assert.equal((await store.readReceipt(request.operation_id)).status, "missing");
    let lost = false;
    const unavailable = new Proxy(store, {get(target, property) {
      if (property === "commitAuthority") return async (commit: AuthorityStoreCommit) => {
        await target.commitAuthority(commit); lost = true; throw new Error("lost response");
      };
      if (property === "readReceipt") return async (id: string) => {
        if (lost) throw new Error("readback unavailable"); return target.readReceipt(id);
      };
      const value = Reflect.get(target, property); return typeof value === "function" ? value.bind(target) : value;
    }});
    assert.equal((await executeCoordinationTodoUpdate(unavailable, request)).status, "ambiguous");
    const committed = await contender.loadAuthority();
    assert.equal((await executeCoordinationTodoUpdate(contender, request)).status, "replayed");
    assert.deepEqual(await store.loadAuthority(), committed);
  });
}
