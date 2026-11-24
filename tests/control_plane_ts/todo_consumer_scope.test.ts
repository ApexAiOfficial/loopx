import assert from "node:assert/strict";
import test from "node:test";
import {projectTodoSummaryLanes} from "../../loopx/control_plane/todos/summary_lanes.ts";
import type {JsonObject} from "../../loopx/control_plane/effect_program.ts";

const row = (todo_id: string, fields: JsonObject = {}): JsonObject => ({todo_id,
  status: "open", done: false, task_class: "user_gate", has_resume: false,
  resume_ready: null, resume_evaluated: false, acceptance_blocked: false,
  claimed: false, preferred: false, watch_only: false, due_at: null, expires_at: null,
  sort: [1, 1, "", todo_id], claim: null, bound: null, blocks: null, global: false,
  excluded: [], ...fields});
const project = (rows: JsonObject[], selection: JsonObject = {}) => projectTodoSummaryLanes({
  schema_version: "todo_summary_lanes_request_v1", rows, observed_at: 100,
  selection: {role: "user", status: null, todo_id: null, agent_id: "agent-a", ...selection}});

test("Agent read selection uses gate and action addressing, before lanes/counts", () => {
  const rows = [row("todo_peer", {claim: "agent-b", claimed: true}),
    row("todo_explicit", {claim: "agent-b", claimed: true, blocks: "agent-a"}),
    row("todo_global", {claim: "agent-b", global: true, excluded: ["agent-a"]}),
    row("todo_action_peer", {task_class: "user_action", claim: "agent-b"}),
    row("todo_action_bound", {task_class: "user_action", claim: "agent-b", bound: "agent-a"}),
    row("todo_legacy")];
  const before = structuredClone(rows), result = project(rows);
  assert.deepEqual(result.source_indices, [1, 2, 4, 5]);
  assert.deepEqual((result.lanes as JsonObject).open_items, [1, 2, 4, 5]);
  assert.equal((result.work_counts as JsonObject).open, 4);
  assert.equal(result.full_selection, false);
  assert.deepEqual(rows, before);
  assert.deepEqual(project(rows, {agent_id: null}).source_indices, [0, 1, 2, 3, 4, 5]);
});

test("filters compose without renumbering source ordinals or losing full-source evaluation", () => {
  const rows = [row("todo_done", {status: "done", done: true}),
    row("todo_ready", {task_class: "advancement_task", claim: "agent-a", claimed: true,
      has_resume: true, resume_ready: true, resume_evaluated: true}),
    row("todo_blocked", {task_class: "blocker", status: "blocked"}),
    row("todo_other", {task_class: "advancement_task", claim: "agent-b"}),
    row("todo_excluded", {task_class: "advancement_task", excluded: ["agent-a"]})];
  const result = project(rows, {role: "agent", status: "open", todo_id: "todo_ready"});
  assert.deepEqual(result.source_indices, [1]);
  assert.deepEqual((result.lanes as JsonObject).executable_items, [1]);
  assert.equal((result.work_counts as JsonObject).advancement, 1);
  assert.deepEqual(project(rows, {role: "agent", todo_id: "todo_other"}).source_indices, []);
  assert.deepEqual(project(rows, {role: "agent", todo_id: "todo_excluded"}).source_indices, []);
});

test("unfiltered v1 preserves v0 lane algebra and rejects malformed selection", () => {
  const rows = [row("todo_a"), row("todo_b", {status: "done", done: true})];
  const v0 = projectTodoSummaryLanes({schema_version: "todo_summary_lanes_request_v0", rows, observed_at: 100});
  const v1 = project(rows, {agent_id: null});
  assert.deepEqual(v1.lanes, v0.lanes); assert.deepEqual(v1.work_counts, v0.work_counts);
  assert.equal(v1.full_selection, true);
  for (const selection of [{role: "other"}, {status: "finished"}, {agent_id: 1}, {todo_id: []}]) {
    assert.throws(() => project(rows, selection));
  }
  assert.throws(() => project([row("todo_bad", {global: "true"})]));
});
