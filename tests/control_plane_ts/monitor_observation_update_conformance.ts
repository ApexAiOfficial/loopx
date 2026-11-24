/** The same observation/reactivation contract on every real provider. */
import {registerMonitorCycleConformance} from "./monitor_cycle_conformance.ts";
import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import test from "node:test";
import type {JsonObject} from "../../loopx/control_plane/effect_program.ts";
import type {AuthorityStore, AuthorityStoreCommit} from "../../loopx/control_plane/coordination/authority_store.ts";
import {
  canonicalAuthorityObject,
  canonicalAuthoritySha256,
} from "../../loopx/control_plane/coordination/authority_store_codec.ts";
import {executeCoordinationTodoUpdate, type CoordinationTodoUpdateInput} from "../../loopx/control_plane/coordination/todo_update.ts";
import {executeCoordinationMonitorPoll} from "../../loopx/control_plane/coordination/todo_monitor_poll.ts";
import {executeCoordinationTodoTerminalLifecycle} from "../../loopx/control_plane/coordination/todo_terminal_lifecycle.ts";
import {coordinationTodoReadModel} from "../../loopx/control_plane/coordination/coordination_projection.ts";
import {evaluateTodoResumeConditions} from "../../loopx/control_plane/todos/resume_condition.ts";
import type {AuthorityStoreConformanceFactory} from "./authority_store_conformance.ts";
import {
  PRODUCTION_SCALE_VALIDATION_DECLARATION,
  productionScaleCompletedMonitorFixture,
  productionScaleLeasedMonitorFixture,
} from "./production_scale_coordination_fixture.ts";

function request(fixture: ReturnType<typeof productionScaleCompletedMonitorFixture>): CoordinationTodoUpdateInput {
  return {goal_id: String(fixture.projection.goal_id), todo_id: fixture.target,
    expected_role: "agent", actor_agent_id: fixture.actor, registered_agents: fixture.registered_agents,
    operation_id: "reactivate", patch: {}, clear_fields: [], dry_run: false, now: fixture.now,
    planning_intent: {status: "open", no_followup: false, reason: "A new observation cycle"},
    monitor_observation: {generated_at: fixture.now.toISOString(), result_hash: "previous-evidence",
      material_change: true, monitor_effect_id: "reactivate", cadence: "1h"}};
}

async function seed(store: AuthorityStore, projection: JsonObject) {
  assert.equal((await store.commitAuthority({operation_id: "seed", expected_provider_revision: null,
    events: [], receipts: [], next_projection: projection})).status, "applied");
}

function legacyUnscopedTerminalOperationId(goalId: string, todoId: string): string {
  const digest = createHash("sha256").update(
    `loopx-provider-terminal-operation-v0\0complete\0${goalId}\0${todoId}\0unscoped`,
    "utf8",
  ).digest("hex");
  return `todo-terminal:${digest.slice(0, 32)}`;
}

function terminalRequest(
  fixture: ReturnType<typeof productionScaleCompletedMonitorFixture>,
  operationId: string,
) {
  return {
    goal_id: String(fixture.projection.goal_id),
    todo_id: fixture.target,
    expected_role: "agent" as const,
    command: "complete" as const,
    actor_agent_id: fixture.actor,
    registered_agents: fixture.registered_agents,
    lifecycle_grants: [],
    authority_reason: null,
    decision_outcome: null,
    operation_identity: {kind: "explicit" as const, operation_id: operationId},
    lease_idempotency_key: null,
    lease_expected_version: null,
    allow_user_gate_auto_acquire: false,
    requested_no_followup: true,
    requested_completion_turn_key: null,
    requested_completion_identity_source: null,
    linked_successor_todo_ids: [],
    successor_intents: [],
    note: null,
    evidence: null,
    reason: null,
    clear_claim: false,
    validation_declaration: PRODUCTION_SCALE_VALIDATION_DECLARATION,
    validation_declaration_sha256: canonicalAuthoritySha256(
      PRODUCTION_SCALE_VALIDATION_DECLARATION,
    ),
    validation_receipt: {
      schema_version: "issue_fix_validation_command_v0",
      command_label: "production-scale fixture validation",
      exit_code: 0,
      passed: true,
      status: "passed",
      summary: "production scale fixture validation passed",
      stdout_captured: false,
      stderr_captured: false,
      local_path_captured: false,
    },
    completion_policy_request: null,
    dry_run: false,
    now: fixture.now,
  };
}

function implicitMonitorRetryRequest(
  fixture: ReturnType<typeof productionScaleCompletedMonitorFixture>,
  now: Date = fixture.now,
) {
  return {
    ...terminalRequest(fixture, "ignored"),
    operation_identity: {kind: "current_monitor_cycle" as const},
    validation_declaration: null,
    validation_receipt: null,
    now,
  };
}

export function registerMonitorObservationUpdateConformance(provider: string, factory: AuthorityStoreConformanceFactory) {
  registerMonitorCycleConformance(provider, factory);
  for (const schema of ["legacy", "native"] as const) {
    test(`${provider}: Monitor observation update ${schema} reactivates a new cycle and preserves historical replay`, async t => {
      const {store, contender} = await factory(t);
      const fixture = productionScaleCompletedMonitorFixture("monitor-reactivation", schema);
      await seed(store, fixture.projection);
      const input = request(fixture);
      const before = await store.loadAuthority();
      const preview = await executeCoordinationTodoUpdate(store, {...input, dry_run: true});
      assert.equal(preview.status, "planned", JSON.stringify(preview));
      assert.equal((preview.monitor_poll_transition as JsonObject).material_change_generation, 5);
      assert.deepEqual(await store.loadAuthority(), before);
      const result = await executeCoordinationTodoUpdate(store, input);
      assert.equal(result.status, "applied", JSON.stringify(result));
      const head = await store.loadAuthority();
      assert.equal(head.status, "loaded"); if (head.status !== "loaded") return;
      const original = fixture.projection.todos as JsonObject[];
      const todos = head.head.todos as JsonObject[];
      const monitor = todos.find(todo => todo.todo_id === fixture.target)!;
      assert.equal(monitor.status, "open"); assert.equal(monitor.done, false);
      assert.equal(monitor.result_hash, "previous-evidence", "equal hashes do not erase a new lifecycle");
      assert.equal(monitor.material_change_generation, 5);
      for (const field of ["completed_at", "no_followup", "completion_continuation", "completion_recovery", "completion_turn_key"]) {
        assert.equal(Object.hasOwn(monitor, field), false, field);
      }
      assert.deepEqual(head.head.leases, fixture.projection.leases);
      assert.deepEqual(todos.filter(todo => todo.todo_id !== fixture.target), original.filter(todo => todo.todo_id !== fixture.target));
      const satisfied = [original, todos].map(source => {
        const result = evaluateTodoResumeConditions({schema_version: "todo_resume_evaluation_request_v0",
          items: source.filter(todo => todo.todo_id === fixture.dependent), source_items: source, kinds: ["monitor_changed"]});
        return ((result.conditions as JsonObject[])[0]!.condition as JsonObject).satisfied;
      });
      assert.deepEqual(satisfied, [false, true]);
      // The normal quota poll still owns subsequent observations and successors.
      const poll = await executeCoordinationMonitorPoll(contender, {goal_id: input.goal_id,
        operation_id: "next-poll", actor_agent_id: input.actor_agent_id, registered_agents: input.registered_agents,
        dry_run: false, observation: {todo_id: fixture.target, generated_at: "2026-09-01T02:00:00Z",
          result_hash: "later-evidence", material_change: true}, intent: {}});
      assert.equal(poll.status, "applied", JSON.stringify(poll));
      assert.equal((poll.writeback as JsonObject).material_change_generation, 6);
      const current = await store.loadAuthority();
      assert.equal(current.status, "loaded"); if (current.status !== "loaded") return;
      const retired = (current.head.todos as JsonObject[]).map(todo => todo.todo_id === fixture.target
        ? {...todo, status: "done", done: true, completed_at: "2026-09-01T03:00:00Z"} : todo);
      await contender.commitAuthority({operation_id: "retire-again", expected_provider_revision: current.provider_revision,
        events: [], receipts: [], next_projection: {...current.head, todos: retired,
          todo_read_model: coordinationTodoReadModel(retired, (current.head.todo_read_model as JsonObject).schema_version)}});
      const final = await store.loadAuthority();
      const replay = await executeCoordinationTodoUpdate(contender, input);
      assert.equal(replay.status, "replayed");
      assert.equal((replay.monitor_poll_transition as JsonObject).material_change_generation, 5);
      assert.deepEqual(await store.loadAuthority(), final, "historical success never reopens current completion");
      const stale = await executeCoordinationTodoUpdate(store, {...input, operation_id: "old-observation-new-id"});
      assert.equal(stale.status, "failed"); assert.match(String(stale.reason), /newer than completion/);
      const conflict = await executeCoordinationTodoUpdate(store, {...input,
        monitor_observation: {...input.monitor_observation!, result_hash: "changed-retry"}});
      assert.equal(conflict.status, "failed");
      assert.deepEqual(await store.loadAuthority(), final);
    });
  }

  test(`${provider}: Monitor observation update rejects invalid authority, effects and stale reactivation without writes`, async t => {
    const {store} = await factory(t);
    const fixture = productionScaleCompletedMonitorFixture("monitor-update-negatives");
    await seed(store, fixture.projection);
    const input = request(fixture), before = await store.loadAuthority();
    const invalid: Partial<CoordinationTodoUpdateInput>[] = [
      {actor_agent_id: null}, {actor_agent_id: "agent-b"}, {registered_agents: []},
      {planning_intent: {}}, {planning_intent: {status: "done"}},
      {planning_intent: {status: "open", claimed_by: "agent-b"}},
      {planning_intent: {status: "open", monitor_metadata: {watch_only: false}}},
      {patch: {text: "No mixed edit"}}, {clear_fields: ["note"]},
      {monitor_observation: {...input.monitor_observation!, material_change: false}},
      {monitor_observation: {...input.monitor_observation!, generated_at: "2026-09-01T00:30:00Z"}},
      {monitor_observation: {...input.monitor_observation!, material_change_generation: 900}},
      {monitor_observation: {...input.monitor_observation!, target_key: "different-target"}},
      {expected_provider_revision: "stale-revision"},
    ];
    for (const mutation of invalid) {
      const result = await executeCoordinationTodoUpdate(store, {...input, ...mutation});
      assert.equal(result.status, "failed", JSON.stringify({mutation, result}));
      assert.deepEqual(await store.loadAuthority(), before);
      assert.equal((await store.readReceipt(input.operation_id)).status, "missing");
    }
    assert.equal((await executeCoordinationTodoUpdate(store, input, async () => false)).status, "failed");
    assert.deepEqual(await store.loadAuthority(), before);
    for (const [index, fields] of [
      {archive_state: "archive"}, {superseded_by: "other-work"}, {excluded_agents: [fixture.actor]},
      {bound_agent: "agent-b"}, {completed_at: "invalid"}, {role: "user", task_class: "user_action"},
    ].entries()) {
      const loaded = await store.loadAuthority(); assert.equal(loaded.status, "loaded");
      if (loaded.status !== "loaded") return;
      const todos = (fixture.projection.todos as JsonObject[]).map(todo => todo.todo_id === fixture.target ? {...todo, ...fields} : todo);
      assert.equal((await store.commitAuthority({operation_id: `source-negative-${index}`, expected_provider_revision: loaded.provider_revision,
        events: [], receipts: [], next_projection: {...fixture.projection, todos,
          todo_read_model: coordinationTodoReadModel(todos, (fixture.projection.todo_read_model as JsonObject).schema_version)}})).status, "applied");
      const source = await store.loadAuthority();
      assert.equal((await executeCoordinationTodoUpdate(store, input)).status, "failed", JSON.stringify(fields));
      assert.deepEqual(await store.loadAuthority(), source);
    }
  });

  test(`${provider}: Monitor observation update holds the current lease without changing execution`, async t => {
    const {store} = await factory(t);
    const fixture = productionScaleLeasedMonitorFixture("monitor-update-lease");
    await seed(store, fixture.projection);
    const input = {...request(fixture), planning_intent: {reason: "Observed current execution"},
      lease_idempotency_key: fixture.proof.idempotency_key, lease_expected_version: fixture.proof.expected_version,
      monitor_observation: {...request(fixture).monitor_observation!, result_hash: "new-evidence"}};
    const before = await store.loadAuthority();
    for (const extra of [{lease_expected_version: 999}, {lease_idempotency_key: "old-key"},
      {now: new Date("2099-01-01T00:00:00Z")}, {planning_intent: {status: "blocked"}}]) {
      assert.equal((await executeCoordinationTodoUpdate(store, {...input, ...extra})).status, "failed");
      assert.deepEqual(await store.loadAuthority(), before);
    }
    const result = await executeCoordinationTodoUpdate(store, input);
    assert.equal(result.status, "applied", JSON.stringify(result));
    const after = await store.loadAuthority(); assert.equal(after.status, "loaded");
    if (after.status === "loaded") assert.deepEqual(after.head.leases, fixture.projection.leases);
    if (after.status === "loaded") {
      const completed = (after.head.todos as JsonObject[]).map(todo => todo.todo_id === fixture.target ?
        {...todo, status: "done", done: true, completed_at: "2026-09-01T01:30:00Z"} : todo);
      await store.commitAuthority({operation_id: "retained-lease", expected_provider_revision: after.provider_revision,
        events: [], receipts: [], next_projection: {...after.head, todos: completed,
          todo_read_model: coordinationTodoReadModel(completed, (after.head.todo_read_model as JsonObject).schema_version)}});
      const retired = await store.loadAuthority();
      const rejected = await executeCoordinationTodoUpdate(store, {...input, operation_id: "cannot-resume-execution",
        planning_intent: {status: "open"}, monitor_observation: {...input.monitor_observation,
          generated_at: "2026-09-01T02:00:00Z", monitor_effect_id: "next-cycle"}});
      assert.equal(rejected.reason_code, "monitor_reactivation_execution_proof_not_allowed");
      assert.deepEqual(await store.loadAuthority(), retired);
    }
  });

  test(`${provider}: Monitor reactivation CAS and lost-response recovery retain one cycle`, async t => {
    const {store, contender} = await factory(t);
    const fixture = productionScaleCompletedMonitorFixture("monitor-update-recovery");
    await seed(store, fixture.projection);
    const input = request(fixture);
    let lost = false;
    const responseLost = new Proxy(store, {get(target, property) {
      if (property === "commitAuthority") return async (commit: AuthorityStoreCommit) => {
        await target.commitAuthority(commit); lost = true; throw new Error("response lost after commit");
      };
      if (property === "readReceipt") return async (id: string) => {
        if (lost) throw new Error("readback unavailable"); return target.readReceipt(id);
      };
      const value = Reflect.get(target, property); return typeof value === "function" ? value.bind(target) : value;
    }});
    assert.equal((await executeCoordinationTodoUpdate(responseLost, input)).status, "ambiguous");
    const committed = await contender.loadAuthority();
    assert.equal((await executeCoordinationTodoUpdate(contender, input)).status, "replayed");
    assert.deepEqual(await store.loadAuthority(), committed);
    const race = new Proxy(store, {get(target, property) {
      if (property === "commitAuthority") return async (commit: AuthorityStoreCommit) => {
        const current = await contender.loadAuthority();
        assert.equal(current.status, "loaded"); if (current.status !== "loaded") throw new Error("missing head");
        await contender.commitAuthority({operation_id: "competing-write", expected_provider_revision: current.provider_revision,
          events: [], receipts: [], next_projection: current.head});
        return target.commitAuthority(commit);
      };
      const value = Reflect.get(target, property); return typeof value === "function" ? value.bind(target) : value;
    }});
    const next = {...input, operation_id: "raced", planning_intent: {},
      monitor_observation: {...input.monitor_observation!, monitor_effect_id: "raced", result_hash: "new-evidence",
        generated_at: "2026-09-01T02:00:00Z"}};
    assert.equal((await executeCoordinationTodoUpdate(race, next)).status, "conflict");
    assert.equal((await store.readReceipt(next.operation_id)).status, "missing");
  });

  for (const schema of ["legacy", "native"] as const) {
    test(`${provider}: Monitor completion identity advances with each ${schema} lifecycle`, async t => {
      const {store, contender} = await factory(t);
      const fixture = productionScaleCompletedMonitorFixture(
        `monitor-completion-cycle-${schema}`,
        schema,
      );
      await seed(store, fixture.projection);
      const firstReactivation = request(fixture);
      assert.equal(
        (await executeCoordinationTodoUpdate(store, firstReactivation)).status,
        "applied",
      );
      const legacyRequest = terminalRequest(
        fixture,
        legacyUnscopedTerminalOperationId(
          String(fixture.projection.goal_id),
          fixture.target,
        ),
      );
      const legacyCompletion = await executeCoordinationTodoTerminalLifecycle(
        store,
        legacyRequest,
      );
      assert.equal(legacyCompletion.status, "applied", JSON.stringify(legacyCompletion));
      const legacyReplay = await executeCoordinationTodoTerminalLifecycle(
        store,
        legacyRequest,
      );
      assert.equal(legacyReplay.status, "replayed", JSON.stringify(legacyReplay));
      assert.deepEqual(legacyReplay.original_receipt, legacyCompletion.original_receipt);
      const cycleCompletion = await executeCoordinationTodoTerminalLifecycle(
        store,
        implicitMonitorRetryRequest(fixture),
      );
      assert.equal(
        cycleCompletion.status,
        "no_change",
        JSON.stringify(cycleCompletion),
      );
      const cycleReceipt = canonicalAuthorityObject(
        cycleCompletion.original_receipt,
        "cycle completion receipt",
      );
      const legacyReceipt = canonicalAuthorityObject(
        legacyCompletion.original_receipt,
        "legacy completion receipt",
      );
      assert.notEqual(cycleReceipt.operation_id, legacyReceipt.operation_id);
      const cycleReplay = await executeCoordinationTodoTerminalLifecycle(
        store,
        implicitMonitorRetryRequest(fixture),
      );
      assert.equal(cycleReplay.status, "replayed", JSON.stringify(cycleReplay));
      assert.deepEqual(cycleReplay.original_receipt, cycleCompletion.original_receipt);

      const secondReactivation = {
        ...firstReactivation,
        operation_id: "reactivate-next-cycle",
        now: new Date("2026-09-01T02:00:00Z"),
        monitor_observation: {
          ...firstReactivation.monitor_observation,
          generated_at: "2026-09-01T02:00:00Z",
          result_hash: "next-cycle-evidence",
          material_change: true,
          monitor_effect_id: "reactivate-next-cycle",
        },
      };
      let reactivated = false;
      const racedReceipt = new Proxy(store, {get(target, property) {
        if (property === "readReceipt") return async (operationId: string) => {
          if (!reactivated && operationId === cycleReceipt.operation_id) {
            reactivated = true;
            assert.equal(
              (await executeCoordinationTodoUpdate(
                contender,
                secondReactivation,
              )).status,
              "applied",
            );
          }
          return target.readReceipt(operationId);
        };
        const value = Reflect.get(target, property);
        return typeof value === "function" ? value.bind(target) : value;
      }});
      const secondCompletion = await executeCoordinationTodoTerminalLifecycle(
        racedReceipt,
        {...terminalRequest(fixture, "ignored"), operation_identity: {kind: "current_monitor_cycle" as const},
          now: secondReactivation.now},
      );
      assert.equal(reactivated, true);
      assert.equal(secondCompletion.status, "applied", JSON.stringify(secondCompletion));
      const secondReceipt = canonicalAuthorityObject(
        secondCompletion.original_receipt,
        "second completion receipt",
      );
      assert.notEqual(
        secondReceipt.operation_id,
        cycleReceipt.operation_id,
      );
      const secondReplay = await executeCoordinationTodoTerminalLifecycle(
        store,
        implicitMonitorRetryRequest(fixture, secondReactivation.now),
      );
      assert.equal(secondReplay.status, "replayed", JSON.stringify(secondReplay));
      assert.deepEqual(
        secondReplay.original_receipt,
        secondCompletion.original_receipt,
      );
      const final = await store.loadAuthority();
      assert.equal(final.status, "loaded");
      if (final.status !== "loaded") return;
      const target = (final.head.todos as JsonObject[])
        .find(todo => todo.todo_id === fixture.target);
      assert.equal(target?.status, "done");
      assert.equal(target?.material_change_generation, 6);
    });
  }

  test(`${provider}: implicit retry after a later explicit cycle never replays a legacy receipt`, async t => {
    const {store} = await factory(t);
    const fixture = productionScaleCompletedMonitorFixture(
      "monitor-completion-explicit-cycle",
      "native",
    );
    await seed(store, fixture.projection);
    const firstReactivation = request(fixture);
    assert.equal(
      (await executeCoordinationTodoUpdate(store, firstReactivation)).status,
      "applied",
    );
    const legacyRequest = terminalRequest(
      fixture,
      legacyUnscopedTerminalOperationId(
        String(fixture.projection.goal_id),
        fixture.target,
      ),
    );
    const legacyCompletion = await executeCoordinationTodoTerminalLifecycle(
      store,
      legacyRequest,
    );
    assert.equal(legacyCompletion.status, "applied", JSON.stringify(legacyCompletion));
    const secondReactivation = {
      ...firstReactivation,
      operation_id: "reactivate-explicit-cycle",
      now: new Date("2026-09-01T02:00:00Z"),
      monitor_observation: {
        ...firstReactivation.monitor_observation,
        generated_at: "2026-09-01T02:00:00Z",
        result_hash: "explicit-cycle-evidence",
        material_change: true,
        monitor_effect_id: "reactivate-explicit-cycle",
      },
    };
    assert.equal(
      (await executeCoordinationTodoUpdate(store, secondReactivation)).status,
      "applied",
    );
    const explicitCompletion = await executeCoordinationTodoTerminalLifecycle(
      store,
      {...terminalRequest(fixture, "complete-explicit-cycle"),
        now: secondReactivation.now},
    );
    assert.equal(explicitCompletion.status, "applied", JSON.stringify(explicitCompletion));
    const implicit = await executeCoordinationTodoTerminalLifecycle(
      store,
      implicitMonitorRetryRequest(fixture, secondReactivation.now),
    );
    assert.equal(implicit.status, "no_change", JSON.stringify(implicit));
    const implicitReceipt = canonicalAuthorityObject(
      implicit.original_receipt,
      "implicit completion receipt",
    );
    const legacyReceipt = canonicalAuthorityObject(
      legacyCompletion.original_receipt,
      "legacy completion receipt",
    );
    assert.notEqual(implicitReceipt.operation_id, legacyReceipt.operation_id);
    const explicitReceipt = canonicalAuthorityObject(
      explicitCompletion.original_receipt,
      "explicit completion receipt",
    );
    assert.notEqual(implicitReceipt.operation_id, explicitReceipt.operation_id);
    const replay = await executeCoordinationTodoTerminalLifecycle(
      store,
      implicitMonitorRetryRequest(fixture, secondReactivation.now),
    );
    assert.equal(replay.status, "replayed", JSON.stringify(replay));
    assert.deepEqual(replay.original_receipt, implicit.original_receipt);
  });

  test(`${provider}: implicit Monitor completion rejects a non-Monitor target`, async t => {
    const {store} = await factory(t);
    const fixture = productionScaleCompletedMonitorFixture(
      "monitor-completion-non-monitor",
      "native",
    );
    const projection = structuredClone(fixture.projection);
    const target = (projection.todos as JsonObject[])
      .find(todo => todo.todo_id === fixture.target);
    assert.ok(target);
    target.task_class = "advancement_task";
    await seed(store, projection);
    const result = await executeCoordinationTodoTerminalLifecycle(
      store,
      implicitMonitorRetryRequest(fixture),
    );
    assert.equal(result.status, "failed");
    assert.equal(result.reason_code, "implicit_monitor_completion_required");
  });
}
