/** Real providers run the same current-proof, atomicity and recovery contract. */
import assert from "node:assert/strict";
import test from "node:test";
import type {JsonObject} from "../../loopx/control_plane/effect_program.ts";
import type {AuthorityStore, AuthorityStoreCommit} from "../../loopx/control_plane/coordination/authority_store.ts";
import {executeCoordinationMonitorPoll} from "../../loopx/control_plane/coordination/todo_monitor_poll.ts";
import {coordinationTodoReadModel} from "../../loopx/control_plane/coordination/coordination_projection.ts";
import {evaluateTodoResumeConditions} from "../../loopx/control_plane/todos/resume_condition.ts";
import type {AuthorityStoreConformanceFactory} from "./authority_store_conformance.ts";
import {productionScaleLeasedMonitorFixture} from "./production_scale_coordination_fixture.ts";

export function registerLeasedMonitorConformance(provider: string, factory: AuthorityStoreConformanceFactory) {
  for (const schema of ["legacy", "native"] as const) test(`${provider}: leased Monitor ${schema} keeps execution and commits one generation with successors`, async t => {
    const {store, contender} = await factory(t);
    const goal = "leased-monitor";
    const fixture = productionScaleLeasedMonitorFixture(goal, schema);
    assert.equal((await store.commitAuthority({operation_id: "seed", expected_provider_revision: null,
      events: [], receipts: [], next_projection: fixture.projection})).status, "applied");
    const request = {goal_id: goal, operation_id: "poll", actor_agent_id: fixture.actor,
      registered_agents: fixture.registered_agents, now: fixture.now, lease_proof: fixture.proof,
      dry_run: false, observation: {todo_id: fixture.target, generated_at: fixture.now.toISOString(),
        result_hash: "changed-evidence", material_change: true},
      intent: {next_agent_todo: "Validate changed evidence", next_action_kind: "validate",
        next_user_todo: "Review changed evidence", next_user_task_class: "user_action"}};
    const before = await store.loadAuthority();
    for (const extra of [{lease_proof: null}, {lease_proof: {...fixture.proof, expected_version: 999}},
      {lease_proof: {...fixture.proof, idempotency_key: "wrong"}}, {actor_agent_id: "agent-b"},
      {registered_agents: ["agent-b"]}, {now: new Date("2099-01-01T00:00:00Z")}]) {
      const result = await executeCoordinationMonitorPoll(store, {...request, ...extra});
      assert.equal(result.status, "failed", JSON.stringify(result));
      assert.deepEqual(await store.loadAuthority(), before);
    }
    assert.equal((await executeCoordinationMonitorPoll(store, {...request, dry_run: true})).status, "planned");
    assert.deepEqual(await store.loadAuthority(), before);
    const first = await executeCoordinationMonitorPoll(store, request);
    assert.equal(first.status, "applied", JSON.stringify(first));
    const after = await store.loadAuthority();
    assert.equal(after.status, "loaded");
    if (after.status !== "loaded") return;
    const rows = after.head.todos as JsonObject[];
    assert.deepEqual(after.head.leases, fixture.projection.leases);
    const original = fixture.projection.todos as JsonObject[];
    assert.deepEqual(rows.filter(todo => original.some(old => old.todo_id === todo.todo_id) && todo.todo_id !== fixture.target),
      original.filter(todo => todo.todo_id !== fixture.target));
    assert.equal(rows.length, original.length + 2);
    assert.equal(rows.find(todo => todo.todo_id === fixture.target)?.material_change_generation, 5);
    const ready = [original, rows].map(source => {
      const result = evaluateTodoResumeConditions({schema_version: "todo_resume_evaluation_request_v0",
        items: source.filter(todo => todo.todo_id === fixture.dependent), source_items: source,
        kinds: ["monitor_changed"]});
      const condition = (result.conditions as JsonObject[])[0]!.condition as JsonObject;
      return condition.satisfied;
    });
    assert.deepEqual(ready, [false, true], "the committed generation releases the existing dependent's wait");
    const unchanged = await executeCoordinationMonitorPoll(store, {...request, operation_id: "unchanged",
      observation: {...request.observation, generated_at: "2026-09-01T02:00:00Z", material_change: false}, intent: {}});
    assert.equal(unchanged.status, "applied");
    assert.equal((unchanged.writeback as JsonObject).material_change_generation, 5);
    assert.deepEqual((unchanged.writeback as JsonObject).next_todos, []);
    const current = await store.loadAuthority();
    assert.equal(current.status, "loaded");
    if (current.status !== "loaded") return;
    // Execution retirement and Todo archival cannot make historical settlement
    // re-run a poll or require a new execution's proof.
    const retired = (current.head.todos as JsonObject[]).map(todo => todo.todo_id === fixture.target
      ? {...todo, archive_state: "archive", status: "done", done: true} : todo);
    await store.commitAuthority({operation_id: "retire", expected_provider_revision: current.provider_revision,
      events: [], receipts: [], next_projection: {...current.head, todos: retired,
        todo_read_model: coordinationTodoReadModel(retired, (current.head.todo_read_model as JsonObject).schema_version),
        leases: (current.head.leases as JsonObject[]).map(lease => lease.todo_id === fixture.target
          ? {...lease, status: "released"} : lease)}});
    const retiredHead = await store.loadAuthority();
    const replay = await executeCoordinationMonitorPoll(contender, {...request, now: new Date("2099-01-01T00:00:00Z")});
    assert.equal(replay.status, "replayed");
    assert.deepEqual((replay.writeback as JsonObject).next_todos, (first.writeback as JsonObject).next_todos);
    assert.deepEqual(await store.loadAuthority(), retiredHead);
    assert.equal((await executeCoordinationMonitorPoll(store, {...request,
      lease_proof: {...fixture.proof, expected_version: fixture.proof.expected_version + 1}})).reason_code,
    "coordination_operation_identity_mismatch");
  });

  test(`${provider}: leased Monitor recovers a lost commit and rejects a racing renewal`, async t => {
    const {store, contender} = await factory(t);
    const fixture = productionScaleLeasedMonitorFixture("monitor-recovery");
    await store.commitAuthority({operation_id: "seed", expected_provider_revision: null,
      events: [], receipts: [], next_projection: fixture.projection});
    const request = {goal_id: "monitor-recovery", operation_id: "lost-response", actor_agent_id: fixture.actor,
      registered_agents: fixture.registered_agents, now: fixture.now, lease_proof: fixture.proof, dry_run: false,
      observation: {todo_id: fixture.target, generated_at: fixture.now.toISOString(), result_hash: "first", material_change: true},
      intent: {next_agent_todo: "Validate once", next_action_kind: "validate"}};
    let responseLost = false;
    const lost = new Proxy(store, {get(target, property) {
      if (property === "commitAuthority") return async (commit: AuthorityStoreCommit) => {
        await target.commitAuthority(commit); responseLost = true; throw new Error("response lost");
      };
      if (property === "readReceipt") return async (operation: string) => {
        if (responseLost) throw new Error("readback unavailable");
        return target.readReceipt(operation);
      };
      const value = Reflect.get(target, property); return typeof value === "function" ? value.bind(target) : value;
    }}) as AuthorityStore;
    assert.equal((await executeCoordinationMonitorPoll(lost, request)).status, "ambiguous");
    const committed = await store.loadAuthority();
    assert.equal((await executeCoordinationMonitorPoll(contender, request)).status, "replayed");
    assert.deepEqual(await store.loadAuthority(), committed);
    let race = true;
    const renewed = new Proxy(store, {get(target, property) {
      if (property === "commitAuthority") return async (commit: AuthorityStoreCommit) => {
        if (race) {
          race = false;
          const loaded = await contender.loadAuthority();
          assert.equal(loaded.status, "loaded");
          if (loaded.status !== "loaded") throw new Error("missing race source");
          await contender.commitAuthority({operation_id: "renew", expected_provider_revision: loaded.provider_revision,
            events: [], receipts: [], next_projection: {...loaded.head,
              leases: (loaded.head.leases as JsonObject[]).map(lease => lease.todo_id === fixture.target
                ? {...lease, version: fixture.proof.expected_version + 1} : lease)}});
        }
        return target.commitAuthority(commit);
      };
      const value = Reflect.get(target, property); return typeof value === "function" ? value.bind(target) : value;
    }}) as AuthorityStore;
    const next = {...request, operation_id: "racing-poll",
      observation: {...request.observation, generated_at: "2026-09-01T02:00:00Z", result_hash: "second"}, intent: {}};
    const raced = await executeCoordinationMonitorPoll(renewed, next);
    assert.equal(raced.status, "conflict", JSON.stringify(raced));
    assert.equal((await executeCoordinationMonitorPoll(store, next)).status, "failed");
    assert.equal((await store.readReceipt(next.operation_id)).status, "missing");
  });
}
