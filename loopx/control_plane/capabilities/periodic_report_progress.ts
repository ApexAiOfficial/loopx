/** Report selection owns report policy; evaluated Todo facts retain their owner.
 * Ordinals address this exact input snapshot and are never durable identities. */
import {createHash} from 'node:crypto';
import type {JsonObject} from '../effect_program.ts';
import {EffectRuntimeRequestError} from '../effect_runtime_errors.ts';
import {requireJsonObject, requireNonEmptyString, requireBoolean, requireStringLiteral} from '../runtime_decode.ts';
import {parseTodoTimestampMicros} from '../runtime_timestamp.ts';
import {authorityUnicodeCompare} from '../coordination/authority_store_codec.ts';

const META_ACTIONS = new Set(['consume_periodic_report_intent', 'repair_periodic_report_intent_consumption', 'repair_periodic_report_editorial']);
const text = (value: unknown): string => typeof value === 'string' ? value.trim() : '';
function timestamp(value: unknown): bigint | null {
  const raw = text(value);
  // Report facts require an explicit offset. The shared Todo codec otherwise
  // accepts naive timestamps as UTC for legacy compatibility.
  if (!/[T ].*(?:Z|[+-]\d{2}(?::?\d{2})?(?::?\d{2}(?:[.,]\d+)?)?)$/u.test(raw)) return null;
  return parseTodoTimestampMicros(raw);
}
function request(value: unknown, schema: string): JsonObject {
  const input = requireJsonObject(value, 'periodic-report read request');
  if (input.schema_version !== schema || !Array.isArray(input.items)) {
    throw new EffectRuntimeRequestError('periodic-report read request schema/items mismatch');
  }
  const seen = new Set<string>();
  for (const raw of input.items) {
    const row = requireJsonObject(raw, 'periodic-report Todo');
    const id = requireNonEmptyString(row.todo_id, 'todo_id');
    if (seen.has(id)) throw new EffectRuntimeRequestError('periodic-report source contains duplicate Todo identities');
    seen.add(id);
  }
  return input;
}

interface ProgressRow {
  index: number;
  status: 'open' | 'blocked' | 'done' | 'deferred';
  owner: string;
  action: string;
  taskClass: string;
  actionable: boolean;
  updatedAt: bigint | null;
  completedAt: string;
  completedTime: bigint | null;
  observedTime: bigint | null;
}

export function selectPeriodicReportProgress(value: unknown): JsonObject {
  const input = request(value, 'periodic_report_progress_selection_request_v0');
  const agent = requireNonEmptyString(input.agent_id, 'agent_id');
  const stage = timestamp(input.completed_at);
  if (stage === null) throw new EffectRuntimeRequestError('periodic-report stage completion timestamp is invalid');
  const rows: ProgressRow[] = (input.items as JsonObject[]).map((row, index) => {
    const updated = text(row.updated_at), completed = text(row.completed_at) || updated;
    return {index, status: requireStringLiteral(row.status, ['open','blocked','done','deferred'], 'Todo status'),
      owner: text(row.claimed_by), action: text(row.action_kind), taskClass: text(row.task_class),
      actionable: requireBoolean(row.actionable, 'evaluated Todo actionable'),
      updatedAt: timestamp(updated), completedAt: completed, completedTime: timestamp(completed),
      observedTime: updated || completed ? timestamp(updated || completed) : stage};
  }).filter(row => row.owner !== '' && row.observedTime !== null && row.observedTime <= stage);
  const ownFirst = (a: ProgressRow, b: ProgressRow): number => Number(a.owner !== agent) - Number(b.owner !== agent);
  const outcomes = rows.filter(row => row.status === 'done' && !META_ACTIONS.has(row.action))
    .sort((a, b) => {
      const tier = ownFirst(a, b);
      if (tier) return tier;
      const left = a.updatedAt ?? a.completedTime ?? 0n;
      const right = b.updatedAt ?? b.completedTime ?? 0n;
      return left === right ? a.index - b.index : left > right ? -1 : 1;
    }).map((row, rank) => ({row, rank}))
    .filter(({row}) => row.completedTime !== null && row.completedTime <= stage)
    .map(({row, rank}) => ({index: row.index, completed_at: row.completedAt, rank}));
  const next = rows.filter(row => row.actionable && row.status === 'open' &&
    row.taskClass !== 'continuous_monitor' && !META_ACTIONS.has(row.action))
    .sort((a, b) => ownFirst(a, b) || a.index - b.index)[0];
  return {schema_version: 'periodic_report_progress_selection_result_v0', outcomes, next_index: next?.index ?? null};
}

export function selectPeriodicReportApprovalRetry(value: unknown): JsonObject {
  const input = request(value, 'periodic_report_approval_retry_request_v0');
  const agent = requireNonEmptyString(input.agent_id, 'agent_id');
  const scope = requireNonEmptyString(input.approval_scope, 'approval_scope');
  const rows = (input.items as JsonObject[]).filter(row => {
    const decisionScope = row.decision_scope;
    const actualScope = typeof decisionScope === 'object' && decisionScope !== null && !Array.isArray(decisionScope)
      ? ['kind', 'granularity', 'scope_key'].map(key => text((decisionScope as JsonObject)[key])).join(':') : text(decisionScope);
    return row.status === 'done' && ['approve_periodic_report_payload', 'cancel_periodic_report_payload'].includes(text(row.action_kind)) &&
      ['reject', 'cancel'].includes(text(row.decision_outcome)) && actualScope === scope &&
      text(row.bound_agent || row.blocks_agent) === agent && timestamp(row.updated_at) !== null;
  }).sort((a, b) => {
    const left = timestamp(a.updated_at)!, right = timestamp(b.updated_at)!;
    return left === right ? authorityUnicodeCompare(text(a.todo_id), text(b.todo_id)) : left > right ? -1 : 1;
  });
  const row = rows[0];
  // Preserve the existing durable retry key; time parsing only selects a row.
  const revision = row ? createHash('sha256').update(`${row.todo_id}:${row.updated_at}`).digest('hex').slice(0, 16) : null;
  return {schema_version: 'periodic_report_approval_retry_result_v0', revision};
}
