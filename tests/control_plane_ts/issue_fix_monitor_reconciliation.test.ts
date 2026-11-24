import assert from "node:assert/strict";
import {test} from "node:test";
import {planIssueFixMonitorReconciliation as plan, ISSUE_FIX_MONITOR_PLAN_REQUEST} from "../../loopx/control_plane/capabilities/issue_fix_monitor_reconciliation.ts";

const target = "github-pr-state-example--repo-checks-pending";
const action = "issue_fix_pr_state_checks_pending";
const ledger = (member = "example/repo#1", fields = {}) => ({grouped_monitor_projection: {
  materialize_nonempty_bucket_monitor: true, target_key: target, action_kind: action,
  member_key: member, state_bucket: "checks_pending", repository: "example/repo", ...fields}});
const todo = (fields = {}) => ({role: "agent", todo_id: "todo_monitor", target_key: target,
  action_kind: action, task_class: "continuous_monitor", status: "open", archive_state: "active", ...fields});
const request = (fields = {}) => ({schema_version: ISSUE_FIX_MONITOR_PLAN_REQUEST,
  generated_at: "2030-01-01T01:00:00Z", cadence: "30m", ledger_rows: [ledger()], todos: [], ...fields});
const steps = (fields = {}) => plan(request(fields)).steps as Record<string, any>[];

test("one typed plan covers create, unchanged, membership change, complete and reactivation", () => {
  const created = steps()[0];
  assert.equal(created.operation, "add");
  assert.equal(created.text.startsWith("[P"), false, "priority belongs to its explicit argument");
  assert.equal(created.metadata.watch_only, "true");
  const current = todo(created.metadata);
  assert.deepEqual(steps({todos: [current]}), [{operation: "unchanged", target_key: target, todo_id: "todo_monitor"}]);
  const changed = steps({todos: [current], ledger_rows: [ledger(), ledger("example/repo#2")]})[0];
  assert.equal(changed.operation, "observe");
  assert.equal(changed.observation.material_change, true);
  assert.equal(Object.hasOwn(changed.observation, "material_change_generation"), false);
  assert.equal(steps({todos: [current], ledger_rows: []})[0].operation, "complete");
  assert.equal(steps({todos: [todo({...created.metadata, status: "done", completed_at: "2029-12-31T00:00:00Z"})]})[0].operation, "reactivate");
});

test("membership identity is set-based and retains the original Python digest", () => {
  const a = plan(request({ledger_rows: [ledger(), ledger("example/repo#2"), ledger()]}));
  const b = plan(request({ledger_rows: [ledger("example/repo#2"), ledger()]}));
  assert.deepEqual(a, b);
  assert.equal(a.active_member_count, 2);
  // Independently calculated from the documented sorted compact JSON membership.
  assert.equal((a.steps as Record<string, any>[])[0].metadata.result_hash, "7aa53a7c0b9bddf3");
});

test("archived and superseded history cannot hide a current target or be reactivated", () => {
  const historical = todo({todo_id: "todo_history", archive_state: "archive", status: "done"});
  assert.equal(steps({todos: [historical]})[0].operation, "add");
  assert.deepEqual(steps({todos: [historical], ledger_rows: []}), []);
  assert.equal(steps({todos: [todo({superseded_by: "todo_new"})]})[0].operation, "add");
  assert.equal(steps({todos: [historical, todo()]})[0].operation, "observe");
});

test("duplicate active identities fail before a write plan can escape", () => {
  assert.throws(() => steps({todos: [todo(), todo({todo_id: "todo_other"})]}), /ambiguous Monitor target/);
});

for (const field of ["target_key", "action_kind", "state_bucket", "repository", "member_key"]) {
  test(`malformed active bucket ${field} cannot be mistaken for an empty group`, () => {
    assert.throws(() => steps({ledger_rows: [ledger("m", {[field]: ""})]}));
  });
}

test("inconsistent bucket identity is rejected, even with distinct members", () => {
  assert.throws(() => steps({ledger_rows: [ledger(), ledger("m2", {repository: "other/repo"})]}), /conflicting/);
});

test("an older empty observation cannot retire newer membership", () => {
  assert.throws(() => steps({ledger_rows: [], todos: [todo({last_checked_at: "2030-01-01T02:00:00Z"})]}), /older/);
  assert.throws(() => steps({todos: [todo({last_checked_at: "2030-01-01T02:00:00Z"})]}), /older/);
  assert.throws(() => steps({todos: [todo({status: "done", completed_at: "2030-01-01T01:00:00Z"})]}), /follow completion/);
});

test("unrelated Todo families and inactive ledger projections stay outside reconciliation", () => {
  assert.deepEqual(steps({ledger_rows: [], todos: [todo({task_class: "advancement_task"}), todo({role: "user"}),
    todo({action_kind: "another_monitor"})]}), []);
  assert.deepEqual(steps({ledger_rows: [ledger("m", {materialize_nonempty_bucket_monitor: false})]}), []);
});

for (const fields of [{todos: null}, {ledger_rows: null}, {generated_at: "invalid"}, {cadence: "bad"}]) {
  test(`invalid complete input rejects: ${JSON.stringify(fields)}`, () => assert.throws(() => steps(fields)));
}


test("missing or mistyped bucket declaration is unknown, not evidence of emptiness", () => {
  assert.throws(() => steps({ledger_rows: [{}]}));
  assert.throws(() => steps({ledger_rows: [ledger("m", {materialize_nonempty_bucket_monitor: "true"})]}));
});

test("membership digest preserves Python Unicode ordering and ASCII escapes", () => {
  const row = steps({ledger_rows: [ledger("repo/é#1"), ledger("repo/\ue000#2"), ledger("repo/😀#3")]})[0];
  assert.equal(row.metadata.result_hash, "7ca4c6e6d940b704");
});
