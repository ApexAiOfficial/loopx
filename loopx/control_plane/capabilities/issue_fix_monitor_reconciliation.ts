/** Issue-fix owns bucket identity; Todo/lease transactions own authorization and
 * persistence. This complete plan is validated before the adapter starts effects. */
import {createHash} from "node:crypto";
import type {JsonObject} from "../effect_program.ts";
import {requireJsonObject, requireNonEmptyString} from "../runtime_decode.ts";
import {authorityUnicodeCompare} from "../coordination/authority_store_codec.ts";
import {normalizeWriteScopes} from "../work_items/task_lease_acquire.ts";
import {EffectRuntimeRequestError} from "../effect_runtime_errors.ts";
import {parseTodoTimestampMicros} from "../runtime_timestamp.ts";
import {evaluateSchedulerStateTransition, SCHEDULER_STATE_TRANSITION_REQUEST_SCHEMA} from "../scheduler/state_transition_rules.ts";

export const ISSUE_FIX_MONITOR_PLAN_REQUEST = "loopx_issue_fix_monitor_plan_request_v0";
export const ISSUE_FIX_MONITOR_PLAN_RESULT = "loopx_issue_fix_monitor_plan_result_v0";
type Group = {target_key: string; action_kind: string; state_bucket: string; repository: string; members: Set<string>};
type ExistingStep = {target_key: string; todo_id: string};
export type MonitorReconciliationStep =
  | {operation: "add"; target_key: string; text: string; action_kind: string; metadata: JsonObject}
  | (ExistingStep & {operation: "observe" | "reactivate"; write_scopes: string[]; reason: string; observation: JsonObject})
  | (ExistingStep & {operation: "complete"; write_scopes: string[]; evidence: string})
  | (ExistingStep & {operation: "unchanged"});

function fail(message: string): never { throw new EffectRuntimeRequestError(message); }
function text(value: unknown): string { return typeof value === "string" ? value.trim() : ""; }
function rows(value: unknown, label: string): JsonObject[] {
  if (!Array.isArray(value)) return fail(`${label} must be a complete array`);
  return value.map(row => requireJsonObject(row, label));
}
function timestamp(value: unknown, label: string): bigint {
  const parsed = parseTodoTimestampMicros(requireNonEmptyString(value, label));
  return parsed === null ? fail(`${label} must be an ISO timestamp`) : parsed;
}

function groupsFromLedger(ledger: JsonObject[]): Map<string, Group> {
  const groups = new Map<string, Group>();
  for (const row of ledger) {
    const projection = requireJsonObject(row.grouped_monitor_projection, "grouped Monitor projection");
    if (typeof projection.materialize_nonempty_bucket_monitor !== "boolean") {
      fail("Monitor projection must explicitly declare whether its bucket is active");
    }
    if (!projection.materialize_nonempty_bucket_monitor) continue;
    const target = requireNonEmptyString(projection.target_key, "Monitor target_key");
    const member = requireNonEmptyString(projection.member_key, "Monitor member_key");
    const action = requireNonEmptyString(projection.action_kind, "Monitor action_kind");
    const bucket = requireNonEmptyString(projection.state_bucket, "Monitor state_bucket");
    const repository = requireNonEmptyString(projection.repository, "Monitor repository");
    if (!target.startsWith("github-pr-state-") || !action.startsWith("issue_fix_pr_state_")) {
      fail("issue-fix Monitor ledger contains an unrelated target/action namespace");
    }
    const existing = groups.get(target);
    if (existing && (existing.action_kind !== action || existing.state_bucket !== bucket || existing.repository !== repository)) {
      fail(`conflicting Monitor bucket identity for ${target}`);
    }
    const group = existing ?? {target_key: target, action_kind: action, state_bucket: bucket, repository, members: new Set<string>()};
    group.members.add(member);
    groups.set(target, group);
  }
  return groups;
}

export function planIssueFixMonitorReconciliation(value: unknown): JsonObject {
  const request = requireJsonObject(value, "issue-fix Monitor reconciliation");
  if (request.schema_version !== ISSUE_FIX_MONITOR_PLAN_REQUEST || Object.keys(request).some(key =>
      !["schema_version", "generated_at", "cadence", "ledger_rows", "todos"].includes(key))) {
    fail("Monitor reconciliation schema/fields mismatch");
  }
  const generatedAt = requireNonEmptyString(request.generated_at, "generated_at");
  const observedAt = timestamp(generatedAt, "generated_at");
  const cadence = requireNonEmptyString(request.cadence, "cadence");
  const schedule = evaluateSchedulerStateTransition({schema_version: SCHEDULER_STATE_TRANSITION_REQUEST_SCHEMA,
    operation: "monitor_schedule", generated_at: generatedAt, cadence, explicit_next_due_at: null});
  if (schedule.operation !== "monitor_schedule" || schedule.next_due_at === null) {
    return fail("issue-fix grouped monitor cadence must be parseable");
  }
  const groups = groupsFromLedger(rows(request.ledger_rows, "ledger_rows"));
  const existing = new Map<string, JsonObject>();
  for (const item of rows(request.todos, "todos")) {
    const target = text(item.target_key);
    if (item.role !== "agent" || item.task_class !== "continuous_monitor" ||
        !target.startsWith("github-pr-state-") || !text(item.action_kind).startsWith("issue_fix_pr_state_")) continue;
    // Archived/superseded rows remain historical; they cannot shadow active work.
    if (item.archive_state === "archive" || item.superseded_by) continue;
    if (existing.has(target)) fail(`ambiguous Monitor target ${target}; resolve duplicate active Todo identities before reconciliation`);
    requireNonEmptyString(item.todo_id, "Monitor todo_id");
    existing.set(target, item);
  }
  const steps: MonitorReconciliationStep[] = [];
  for (const [target, group] of [...groups].sort(([a], [b]) => authorityUnicodeCompare(a, b))) {
    // Persisted Python identity uses code-point ordering and ensure_ascii=True.
    // UTF-16 default sort / unescaped JSON would invent a membership change.
    const membership = JSON.stringify([...group.members].sort(authorityUnicodeCompare))
      .replace(/[\u0080-\uffff]/g, char => `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`);
    const resultHash = createHash("sha256").update(membership).digest("hex").slice(0, 16);
    const previous = existing.get(target);
    const reopening = previous?.status === "done" || previous?.done === true;
    const material = reopening || text(previous?.result_hash) !== resultHash;
    if (!previous) {
      steps.push({operation: "add", target_key: target, action_kind: group.action_kind,
        text: `Monitor ${group.repository} issue-fix PR lifecycle bucket ${group.state_bucket} for material changes.`,
        metadata: {target_key: target, cadence, next_due_at: schedule.next_due_at, last_checked_at: generatedAt,
          result_hash: resultHash, consecutive_no_change: "0", material_change: "true", watch_only: "true"}});
      continue;
    }
    if (text(previous.action_kind) !== group.action_kind) fail(`Monitor action identity changed for ${target}`);
    const todoId = String(previous.todo_id);
    if (!reopening && !material && text(previous.cadence) === cadence && text(previous.next_due_at)) {
      steps.push({operation: "unchanged", target_key: target, todo_id: todoId});
    } else {
      if (text(previous.last_checked_at) && observedAt < timestamp(previous.last_checked_at, "last_checked_at")) {
        fail(`Monitor observation is older than persisted state for ${target}`);
      }
      if (reopening && observedAt <= timestamp(previous.completed_at, "completed_at")) {
        fail(`Monitor reactivation must follow completion for ${target}`);
      }
      steps.push({operation: reopening ? "reactivate" : "observe", target_key: target, todo_id: todoId,
        write_scopes: normalizeWriteScopes(previous.required_write_scopes),
        reason: `Issue-fix PR lifecycle bucket ${group.state_bucket} contains ${group.members.size} active member(s).`,
        observation: {generated_at: generatedAt, result_hash: resultHash, material_change: material,
          target_key: target, cadence, next_due_at: schedule.next_due_at}});
    }
  }
  for (const [target, previous] of [...existing].sort(([a], [b]) => authorityUnicodeCompare(a, b))) {
    if (groups.has(target) || previous.status === "done" || previous.done === true) continue;
    // An older empty ledger is not proof that a newer observed group is empty.
    if (text(previous.last_checked_at) && observedAt < timestamp(previous.last_checked_at, "last_checked_at")) {
      fail(`empty Monitor observation is older than persisted state for ${target}`);
    }
    steps.push({operation: "complete", target_key: target, todo_id: String(previous.todo_id),
      write_scopes: normalizeWriteScopes(previous.required_write_scopes),
      evidence: `Issue-fix PR lifecycle bucket ${target} is empty.`});
  }
  return {schema_version: ISSUE_FIX_MONITOR_PLAN_RESULT, steps,
    active_bucket_count: groups.size, active_member_count: [...groups.values()].reduce((n, group) => n + group.members.size, 0),
    next_due_at: groups.size ? schedule.next_due_at : null};
}
