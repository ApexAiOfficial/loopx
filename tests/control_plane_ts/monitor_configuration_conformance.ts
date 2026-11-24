/** Configuration is a Todo transaction, never a poll or a generation advance. */
import assert from "node:assert/strict";
import test from "node:test";
import type {JsonObject} from "../../loopx/control_plane/effect_program.ts";
import type {AuthorityStore} from "../../loopx/control_plane/coordination/authority_store.ts";
import {canonicalAuthoritySha256} from "../../loopx/control_plane/coordination/authority_store_codec.ts";
import {executeCoordinationTodoUpdate} from "../../loopx/control_plane/coordination/todo_update.ts";
import type {AuthorityStoreConformanceFactory} from "./authority_store_conformance.ts";
import {productionScaleCoordinationFixture} from "./production_scale_coordination_fixture.ts";

export function registerMonitorConfigurationConformance(provider: string, factory: AuthorityStoreConformanceFactory) {
  for (const leased of [false, true]) test(`${provider}: Monitor configuration preserves complete history and ${leased ? "current lease" : "receipt replay"}`, async t => {
    const {store, contender} = await factory(t);
    const goal = "monitor-config";
    const fixture = productionScaleCoordinationFixture(goal);
    const projection = structuredClone(fixture.projection) as JsonObject;
    const todos = projection.todos as JsonObject[];
    const leases = projection.leases as JsonObject[];
    // Extend one existing live leased task into the Monitor dimension; keep
    // every other task, dependency and lease from the complete fixture.
    const monitor = todos.find(todo => leased ? todo.todo_id === fixture.completion_todo_id :
      todo.task_class === "continuous_monitor" && todo.status === "open" &&
      !leases.some(lease => lease.todo_id === todo.todo_id))!;
    assert.ok(monitor, "complete fixture needs a live task for configuration");
    const lease = leases.find(lease => lease.todo_id === monitor.todo_id);
    const actor = leased ? String(lease!.owner) : "agent-a";
    Object.assign(monitor, {task_class: "continuous_monitor", claimed_by: actor, watch_only: "true", target_key: "configuration-target",
      cadence: "1h", result_hash: "observed-state", material_change_generation: 7, last_checked_at: "2025-01-01T00:00:00Z"});
    delete monitor.excluded_agents;
    delete monitor.bound_agent;
    projection.handoff_mode = "soft_claim";
    (projection.todo_read_model as JsonObject).records_sha256 = canonicalAuthoritySha256(todos);
    assert.equal((await store.commitAuthority({operation_id: "seed-monitor", expected_provider_revision: null,
      next_projection: projection, events: [], receipts: []})).status, "applied");
    const before = await store.loadAuthority();
    assert.equal(before.status, "loaded");
    if (before.status !== "loaded") throw new Error("seed missing");
    const request = {goal_id: goal, todo_id: String(monitor.todo_id), expected_role: "agent", actor_agent_id: actor,
      registered_agents: fixture.registered_agents, operation_id: "configure-monitor", patch: {}, clear_fields: [],
      dry_run: false, now: leased ? new Date(new Date(String(lease!.expires_at)).getTime() - 60000) : new Date("2099-01-01T00:00:00Z"),
      planning_intent: {monitor_metadata: {cadence: "2h", watch_only: "TRUE"}},
      ...(leased ? {lease_idempotency_key: String(lease!.idempotency_key), lease_expected_version: Number(lease!.version)} : {})};
    if (leased) {
      assert.equal((await executeCoordinationTodoUpdate(store, {...request, lease_idempotency_key: null, lease_expected_version: null})).status, "failed");
      assert.deepEqual(await store.loadAuthority(), before);
    }
    assert.equal((await executeCoordinationTodoUpdate(store, {...request, dry_run: true})).status, "planned");
    assert.deepEqual(await store.loadAuthority(), before);
    const applied = await executeCoordinationTodoUpdate(store, request);
    assert.equal(applied.status, "applied", JSON.stringify(applied));
    let after = await store.loadAuthority();
    if (after.status !== "loaded") throw new Error("committed head missing");
    assert.deepEqual(after.head.leases, projection.leases);
    const actual = (after.head.todos as JsonObject[]).find(todo => todo.todo_id === monitor.todo_id)!;
    assert.equal(actual.cadence, "2h");
    assert.equal(actual.material_change_generation, 7);
    assert.equal(actual.result_hash, "observed-state");
    assert.equal(actual.last_checked_at, monitor.last_checked_at);
    assert.deepEqual((after.head.todos as JsonObject[]).filter(todo => todo.todo_id !== monitor.todo_id),
      todos.filter(todo => todo.todo_id !== monitor.todo_id));
    assert.equal((await executeCoordinationTodoUpdate(store, {...request,
      planning_intent: {monitor_metadata: {cadence: "2h", watch_only: true}}})).status, "replayed");
    assert.deepEqual(await store.loadAuthority(), after);
    for (const metadata of [{result_hash: "fabricated"}, {material_change_generation: 9}, {watch_only: null},
      {target_key: "different-target"}, {target_key: null}, {cadence: []}, {cadence: "never"}, {unknown: "x"}]) {
      const result = await executeCoordinationTodoUpdate(store, {...request, operation_id: "illegal", patch: {text: "Partial edit"},
        planning_intent: {monitor_metadata: metadata}});
      assert.equal(result.status, "failed", JSON.stringify(result));
      assert.equal((await store.readReceipt("illegal")).status, "missing");
      assert.deepEqual(await store.loadAuthority(), after);
    }
    assert.equal((await executeCoordinationTodoUpdate(store, {...request, operation_id: "wrong-actor", actor_agent_id: "agent-foreign"})).status, "failed");
    assert.equal((await executeCoordinationTodoUpdate(store, {...request, operation_id: "no-change"})).status, "no_change");
    // Configuration and the receipt use one CAS. A competing observation cannot be overwritten.
    const stale = before.provider_revision;
    assert.equal((await executeCoordinationTodoUpdate(contender, {...request, operation_id: "stale",
      expected_provider_revision: stale})).reason_code, "provider_revision_mismatch");
    const lost: AuthorityStore = {storeIdentity: store.storeIdentity,
      loadAuthority: () => store.loadAuthority(), readReceipt: key => store.readReceipt(key),
      scanCommitted: (cursor, limit) => store.scanCommitted(cursor, limit), async commitAuthority(value) {
        await store.commitAuthority(value); throw new Error("synthetic response lost");
      }};
    const next = {...request, operation_id: "lost-config", planning_intent: {monitor_metadata: {cadence: "3h"}}};
    assert.equal((await executeCoordinationTodoUpdate(lost, next)).status, "recovered");
    after = await store.loadAuthority();
    assert.equal((await executeCoordinationTodoUpdate(contender, next)).status, "replayed");
    assert.deepEqual(await store.loadAuthority(), after);
  });
}
