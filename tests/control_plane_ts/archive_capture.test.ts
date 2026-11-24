import assert from "node:assert/strict";
import test from "node:test";
import {captureArchivedTodoDependencies as capture, ARCHIVE_CAPTURE_REQUEST_SCHEMA} from
  "../../loopx/control_plane/todos/archive_capture.ts";

const dependency = {todo_id: "todo_history", archive_state: "archive", status: "done", done: true,
  task_class: "advancement_task", text: "Historical work"};
const request = (archived: object[], active: object[] = [{todo_id: "todo_active", resume_when: "todo_done:todo_history"}]) =>
  ({schema_version: ARCHIVE_CAPTURE_REQUEST_SCHEMA, active, archived});

test("capture carries actual transitive archive nodes, not cached readiness or unrelated history", () => {
  assert.deepEqual(capture(request([{...dependency, resume_when: "todo_done:todo_prior"},
    {...dependency, todo_id: "todo_prior"}, {...dependency, todo_id: "todo_unrelated"}])),
  {schema_version: "todo_archive_dependency_capture_result_v1", records: [{index: 0, role: "agent", task_class: "advancement_task"}, {index: 1, role: "agent", task_class: "advancement_task"}]});
  assert.deepEqual(capture(request([], [{todo_id: "todo_active", resume_when: "todo_done:todo_history", resume_ready: true}])).records, []);
});

test("capture never invents user decision authority from class, text, or cached conditions", () => {
  for (const changed of [{task_class: "user_gate"}, {task_class: "user_action"}, {task_class: undefined},
    {role: "user"}, {role: "unknown"}, {global_gate: true}, {decision_outcome: "approve"},
    {status: "open", done: false}, {archive_state: "active"}]) {
    assert.throws(() => capture(request([{...dependency, ...changed}])), /archive dependency capture/);
  }
  assert.deepEqual(capture(request([{...dependency, role: "user", task_class: "user_action"}])).records,
    [{index: 0, role: "user", task_class: "user_action"}]);
});

test("capture preserves unreferenced archived standing decisions and their revocations", () => {
  const standing = (todo_id: string, decision_outcome: string) => ({todo_id, role: "user",
    task_class: "user_gate", status: "done", done: true, archive_state: "archive", global_gate: true,
    decision_scope: {kind: "write_scope", granularity: "goal", scope_key: "release"}, decision_outcome});
  assert.deepEqual(capture(request([
    standing("todo_approve", "approve"), standing("todo_reject", "reject"), standing("todo_cancel", "cancel"),
    {...standing("todo_linked", "approve"), unblocks_todo_id: "todo_delivery"},
  ], [{todo_id: "todo_delivery"}])).records,
  [{index: 0, role: "user", task_class: "user_gate"}, {index: 1, role: "user", task_class: "user_gate"}, {index: 2, role: "user", task_class: "user_gate"}]);
  assert.throws(() => capture(request([standing("todo_reject", "reject"), standing("todo_reject", "reject")],
    [{todo_id: "todo_delivery"}])), /duplicate standing decision identity/);
});

test("duplicate identities cannot be selected by storage order; archived cycles terminate", () => {
  assert.throws(() => capture(request([dependency, dependency])), /duplicate dependency identity/);
  assert.throws(() => capture(request([dependency], [{todo_id: "todo_history", resume_when: "todo_done:todo_history"}])), /duplicate/);
  assert.deepEqual(capture(request([{...dependency, resume_when: "todo_done:todo_history"}])).records,
    [{index: 0, role: "agent", task_class: "advancement_task"}]);
});

test("capture retains explicit and inferred archived continuations through the same edge index", () => {
  const active = [{todo_id: "todo_active", successor_todo_ids: ["todo_explicit"], superseded_by: "todo_replaced"}];
  const archived = [{...dependency, todo_id: "todo_explicit"}, {...dependency, todo_id: "todo_replaced"},
    {...dependency, todo_id: "todo_inferred", unblocks_todo_id: "todo_active"},
    {...dependency, todo_id: "todo_transitive", resume_when: "todo_done:todo_inferred"},
    {...dependency, todo_id: "todo_unrelated"}];
  assert.deepEqual(capture(request(archived, active)).records,
    [{index: 1, role: "agent", task_class: "advancement_task"}, {index: 0, role: "agent", task_class: "advancement_task"}, {index: 2, role: "agent", task_class: "advancement_task"}, {index: 3, role: "agent", task_class: "advancement_task"}]);
});

test("deferred successor lineage does not become a completed resume prerequisite", () => {
  const deferred = {...dependency, status: "deferred", done: true};
  assert.deepEqual(capture(request([deferred], [{todo_id: "todo_active", successor_todo_ids: [dependency.todo_id]}])).records,
    [{index: 0, role: "agent", task_class: "advancement_task"}]);
  assert.deepEqual(capture(request([deferred])).records, [{index: 0, role: "agent", task_class: "advancement_task"}]);
  assert.equal(deferred.status, "deferred");
});

test("retained deferred dependencies remain unsatisfied after capture", async () => {
  const {evaluateTodoResumeConditions, TODO_RESUME_EVALUATION_REQUEST_SCHEMA_VERSION} =
    await import("../../loopx/control_plane/todos/resume_condition.ts");
  const historical = {...dependency, role: "agent", status: "deferred", done: true};
  const selection = capture(request([historical]));
  assert.deepEqual(selection.records, [{index: 0, role: "agent", task_class: "advancement_task"}]);
  const result = evaluateTodoResumeConditions({schema_version: TODO_RESUME_EVALUATION_REQUEST_SCHEMA_VERSION,
    items: [{todo_id: "todo_active", role: "agent", status: "open", task_class: "advancement_task", resume_when: "todo_done:todo_history"}],
    source_items: [historical], rollout_events: [], evaluated_at: "2026-09-20T00:00:00Z"});
  assert.equal(((result.conditions as Record<string, unknown>[])[0].condition as Record<string, unknown>).satisfied, false);
});

test("old capture request cannot silently omit the expanded relationship contract", () => {
  for (const schema_version of ["todo_archive_dependency_capture_request_v0", "todo_archive_dependency_capture_request_v1"])
    assert.throws(() => capture({...request([]), schema_version}), /invalid request/);
});

test("recorded Agent role admits the legacy read class without creating authority", () => {
  const historical = {...dependency, role: "agent", task_class: undefined,
    legacy_task_class: "advancement_task", resume_when: "todo_done:todo_prior"};
  const result = capture(request([historical, {...dependency, todo_id: "todo_prior"}]));
  assert.deepEqual(result.records, [
    {index: 0, role: "agent", task_class: "advancement_task"},
    {index: 1, role: "agent", task_class: "advancement_task"},
  ]);
  for (const changed of [{role: undefined}, {role: "user"}, {task_class: "unknown"},
    {task_class: "user_gate"}, {legacy_task_class: undefined}, {legacy_task_class: "user_gate"},
    {global_gate: true}, {decision_outcome: "approve"}]) {
    assert.throws(() => capture(request([{...historical, ...changed}])), /archive dependency capture/);
  }
});

test("legacy classification participates in inferred succession before walking closure", () => {
  const archived = [{...dependency, role: "agent", task_class: undefined,
    legacy_task_class: "advancement_task", unblocks_todo_id: "todo_active"}];
  assert.deepEqual(capture(request(archived, [{todo_id: "todo_active"}])).records,
    [{index: 0, role: "agent", task_class: "advancement_task"}]);
  assert.deepEqual(capture(request([{...archived[0], legacy_task_class: "continuous_monitor"}],
    [{todo_id: "todo_active"}])).records, []);
  // Explicit class wins over a stale legacy projection.
  assert.deepEqual(capture(request([{...archived[0], task_class: "continuous_monitor"}],
    [{todo_id: "todo_active"}])).records, []);
});
