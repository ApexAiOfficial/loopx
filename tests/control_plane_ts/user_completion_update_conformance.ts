import assert from "node:assert/strict";
import test from "node:test";
import type {AuthorityStore} from "../../loopx/control_plane/coordination/authority_store.ts";
import type {JsonObject} from "../../loopx/control_plane/effect_program.ts";
import {executeCoordinationTodoUpdate, type CoordinationTodoUpdateInput} from "../../loopx/control_plane/coordination/todo_update.ts";
import {canonicalAuthoritySha256} from "../../loopx/control_plane/coordination/authority_store_codec.ts";
import {prepareCoordinationProjectionCommit} from "../../loopx/control_plane/coordination/coordination_projection.ts";
import type {AuthorityStoreConformanceFactory} from "./authority_store_conformance.ts";
import {authorityProjectionFixture} from "./authority_projection_fixture.ts";
import {productionScaleCoordinationFixture, PRODUCTION_SCALE_VALIDATION_DECLARATION as declaration} from "./production_scale_coordination_fixture.ts";

async function loaded(store: AuthorityStore) {
  const result = await store.loadAuthority();
  assert.equal(result.status, "loaded");
  if (result.status !== "loaded") throw new Error("fixture authority missing");
  return result;
}
const receipt = {schema_version: "issue_fix_validation_command_v0", command_label: declaration.validation_label,
  passed: true, exit_code: 0, status: "passed", summary: "Synthetic validation passed",
  stdout_captured: false, stderr_captured: false, local_path_captured: false};

export function registerUserCompletionUpdateConformance(provider: string, factory: AuthorityStoreConformanceFactory): void {
  for (const schema of ["legacy", "native"] as const) {
    test(`${provider}: User completion update validates, fences and recovers a complete ${schema} graph`, async t => {
      const {store, contender} = await factory(t);
      const goal = "user-completion";
      const fixture = productionScaleCoordinationFixture(goal, schema);
      const todos = structuredClone(fixture.projection.todos) as JsonObject[];
      const target = todos.find(todo => todo.role === "user" && todo.status === "open" && !todo.decision_scope)!;
      assert.ok(target);
      Object.assign(target, {task_class: "user_gate", bound_agent: "agent-a", blocks_agent: "agent-a",
        claimed_by: "agent-a", completion_validation_required: true,
        completion_validation_sha256: canonicalAuthoritySha256(declaration)});
      const leases = structuredClone(fixture.projection.leases) as JsonObject[];
      const lease = {...leases.find(row => row.todo_id === fixture.completion_todo_id)!,
        todo_id: target.todo_id, write_scopes: [], idempotency_key: "user-execution", version: 3, lease_epoch: 7};
      leases.push(lease);
      const projection = authorityProjectionFixture(goal, todos, leases, schema, {handoff_mode: "hard_lease"});
      assert.equal((await store.commitAuthority({operation_id: "seed", expected_provider_revision: null,
        next_projection: projection, events: [], receipts: []})).status, "applied");
      const before = await loaded(store);
      const request: CoordinationTodoUpdateInput = {goal_id: goal, todo_id: String(target.todo_id), expected_role: "user",
        actor_agent_id: "agent-a", registered_agents: fixture.registered_agents, lifecycle_grants: [],
        operation_id: "user-update", patch: {text: "Validated owner observation", note: "Initial acknowledgement"},
        clear_fields: [], planning_intent: {status: "done", no_followup: true, reason: ""},
        lease_idempotency_key: "user-execution", lease_expected_version: 3,
        completion: {validation_declaration: declaration}, dry_run: false, now: new Date("2026-09-18T06:00:00Z")};
      for (const [label, changes, code] of [
        ["wrong-actor", {actor_agent_id: "agent-b"}, "bound_agent_mismatch"],
        ["stale-lease", {lease_expected_version: 2}, "version_mismatch"],
        ["binding-launder", {planning_intent: {...request.planning_intent, bound_agent: "agent-b"}}, "update_lease_ownership_transition_unsupported"],
        ["wrong-class", {planning_intent: {...request.planning_intent, task_class: "advancement_task"}}, "invalid_coordination_todo_update"],
        ["agent-close", {todo_id: fixture.completion_todo_id, expected_role: "agent"}, "invalid_coordination_todo_update"],
        ["missing-successor", {planning_intent: {...request.planning_intent, no_followup: false, successor_todo_ids: ["todo_missing"]}}, "todo_successor_not_found"],
      ] as const) {
        const result = await executeCoordinationTodoUpdate(store, {...request, ...changes, operation_id: label});
        // Successor topology must be rejected before effects too.
        assert.equal(result.reason_code, code, JSON.stringify(result));
        assert.deepEqual(await loaded(store), before);
        assert.equal((await store.readReceipt(label)).status, "missing");
      }
      assert.equal((await executeCoordinationTodoUpdate(store, {...request, dry_run: true})).status, "planned");
      assert.deepEqual(await loaded(store), before);
      let sourceChecks = 0;
      assert.equal((await executeCoordinationTodoUpdate(store, request, async () => ++sourceChecks === 1)).reason_code,
        "authority_source_changed");
      const effect = await executeCoordinationTodoUpdate(store, request);
      assert.equal(effect.status, "execute_validation", JSON.stringify(effect));
      assert.deepEqual(await loaded(store), before);
      const resume = {...request, completion: {...request.completion,
        validation_receipt: receipt, source_provider_revision: effect.provider_revision}};
      assert.equal((await executeCoordinationTodoUpdate(store, {...resume,
        completion: {...request.completion, validation_receipt: receipt}})).reason_code, "completion_validation_source_required");
      assert.equal((await executeCoordinationTodoUpdate(store, {...resume,
        completion: {...resume.completion, validation_receipt: {...receipt, passed: false, exit_code: 1}}})).reason_code, "validation_failed");
      assert.equal((await executeCoordinationTodoUpdate(store, {...resume, now: new Date("2028-01-01T00:00:00Z")})).reason_code,
        "handoff_mode_requires_lease");
      assert.deepEqual(await loaded(store), before);
      // Another real provider instance changes an unrelated record while the host validates.
      const other = todos.find(todo => todo.todo_id !== target.todo_id)!;
      assert.equal((await contender.commitAuthority(prepareCoordinationProjectionCommit({goal_id: goal,
        operation_id: "concurrent-edit", expected_provider_revision: before.provider_revision,
        projection: before.head, mutations: [{kind: "todo_upsert", todo: {...other, note: "Concurrent observation"}}]}))).status, "applied");
      const advanced = await loaded(store);
      assert.equal((await executeCoordinationTodoUpdate(store, resume)).reason_code, "provider_revision_mismatch");
      assert.deepEqual(await loaded(store), advanced);
      const freshEffect = await executeCoordinationTodoUpdate(store, request);
      const freshResume = {...resume, completion: {...resume.completion, source_provider_revision: freshEffect.provider_revision}};
      const applied = await executeCoordinationTodoUpdate(store, freshResume);
      assert.equal(applied.status, "applied", JSON.stringify(applied));
      const after = await loaded(store);
      const completed = (after.head.todos as JsonObject[]).find(todo => todo.todo_id === target.todo_id)!;
      assert.equal(completed.status, "done");
      assert.equal(completed.text, request.patch.text);
      const retired = (after.head.leases as JsonObject[]).find(row => row.todo_id === target.todo_id)!;
      assert.deepEqual(retired, {...lease, status: "released", updated_at: "2026-09-18T06:00:00Z"});
      assert.equal(retired.status, "released");
      assert.equal(retired.version, 3);
      assert.equal(retired.lease_epoch, 7);
      assert.deepEqual((after.head.todos as JsonObject[]).filter(todo => todo.todo_id !== target.todo_id),
        (advanced.head.todos as JsonObject[]).filter(todo => todo.todo_id !== target.todo_id));
      const original = await store.readReceipt(request.operation_id);
      assert.equal((await executeCoordinationTodoUpdate(contender, freshResume,
        async () => {throw new Error("history must precede current admission");})).status, "replayed");
      assert.deepEqual(await loaded(store), after);
      assert.deepEqual(await store.readReceipt(request.operation_id), original);
      assert.equal((await executeCoordinationTodoUpdate(store, {...freshResume, patch: {note: "Different intent"}})).reason_code,
        "coordination_operation_identity_mismatch");
      const annotation = await executeCoordinationTodoUpdate(store, {...request, operation_id: "annotation",
        patch: {note: "Later acknowledgement"}, lease_idempotency_key: null, lease_expected_version: null});
      assert.equal(annotation.status, "applied", JSON.stringify(annotation));
      const annotated = await loaded(store);
      const annotatedTodo = (annotated.head.todos as JsonObject[]).find(todo => todo.todo_id === target.todo_id)!;
      assert.equal(annotatedTodo.note, "Later acknowledgement");
      assert.equal(annotatedTodo.completed_at, completed.completed_at);
      assert.deepEqual(annotated.head.leases, after.head.leases);
    });
  }
  test(`${provider}: User completion cannot turn update-only delegation into terminal authority`, async t => {
    const {store} = await factory(t);
    const projection = authorityProjectionFixture("delegated-completion", [{todo_id: "todo_user", role: "user",
      task_class: "user_action", status: "open", done: false, archive_state: "active", text: "Record an outcome",
      claimed_by: "agent-b"}], [], "native", {handoff_mode: "soft_claim"});
    await store.commitAuthority({operation_id: "seed", expected_provider_revision: null, next_projection: projection, events: [], receipts: []});
    const before = await loaded(store);
    const request: CoordinationTodoUpdateInput = {goal_id: "delegated-completion", todo_id: "todo_user", expected_role: "user",
      actor_agent_id: "agent-a", registered_agents: ["agent-a", "agent-b"],
      lifecycle_grants: [{agent_id: "agent-a", actions: ["update"], requires_reason: true}],
      authority_reason: "Reviewed correction", operation_id: "delegated", patch: {note: "Acknowledged"}, clear_fields: [],
      planning_intent: {status: "done", clear_claim: true, no_followup: true}, completion: {}, dry_run: false, now: new Date("2026-09-18T06:00:00Z")};
    const denied = await executeCoordinationTodoUpdate(store, request);
    assert.equal(denied.reason_code, "delegation_action_not_granted");
    assert.deepEqual(await loaded(store), before);
    assert.equal((await store.readReceipt(request.operation_id)).status, "missing");
    const accepted = await executeCoordinationTodoUpdate(store, {...request,
      lifecycle_grants: [{agent_id: "agent-a", actions: ["update", "complete"], requires_reason: true}]});
    assert.equal(accepted.status, "applied", JSON.stringify(accepted));
    const after = await loaded(store);
    const todo = (after.head.todos as JsonObject[])[0];
    assert.equal(todo.status, "done");
    assert.equal(Object.hasOwn(todo, "claimed_by"), false);
  });

}
