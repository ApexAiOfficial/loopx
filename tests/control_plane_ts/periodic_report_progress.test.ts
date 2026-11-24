import assert from 'node:assert/strict';
import test from 'node:test';
import {createHash} from 'node:crypto';
import {selectPeriodicReportProgress, selectPeriodicReportApprovalRetry} from '../../loopx/control_plane/capabilities/periodic_report_progress.ts';
import type {JsonObject} from '../../loopx/control_plane/effect_program.ts';

const row = (id: string, extra: JsonObject = {}): JsonObject => ({todo_id:id, claimed_by:'writer',
  status:'done', updated_at:'2026-09-21T10:00:00Z', task_class:'advancement_task', actionable:false, ...extra});
const progress = (items: JsonObject[], completed_at='2026-09-21T12:00:00Z') => selectPeriodicReportProgress({
  schema_version:'periodic_report_progress_selection_request_v0', agent_id:'writer', completed_at, items});

test('report selection orders actual instants and preserves sub-millisecond ordering', () => {
  const result = progress([row('a',{updated_at:'2026-09-21T18:00:00+08:00'}),
    row('b',{updated_at:'2026-09-21T10:00:00.000002Z'}), row('c',{updated_at:'2026-09-21T10:00:00.000001Z'})]);
  assert.deepEqual((result.outcomes as JsonObject[]).map(r => r.index), [1,2,0]);
});

test('report stage is inclusive at the exact microsecond, not a millisecond bucket', () => {
  const result = progress([row('a',{updated_at:'2026-09-21T10:00:00.000001Z'}),
    row('b',{updated_at:'2026-09-21T10:00:00.000002Z'})], '2026-09-21T10:00:00.000001Z');
  assert.deepEqual((result.outcomes as JsonObject[]).map(r => r.index), [0]);
});

test('report selection retains peer progress and prioritizes reporter, never unowned work', () => {
  const result = progress([row('peer',{claimed_by:'peer', updated_at:'2026-09-21T11:00:00Z'}), row('own'), row('unowned',{claimed_by:null})]);
  assert.deepEqual((result.outcomes as JsonObject[]).map(r => r.index), [1,0]);
});

test('report next action obeys evaluated authority and excludes all report repair tasks', () => {
  const result = progress([row('held',{status:'open',actionable:false}),
    row('monitor',{status:'open',actionable:true,task_class:'continuous_monitor'}),
    row('editorial',{status:'open',actionable:true,action_kind:'repair_periodic_report_editorial'}),
    row('next',{status:'open',actionable:true})]);
  assert.equal(result.next_index,3);
});

for (const value of ['2026-09-21T10:00:00','2026-02-30T10:00:00Z','bad']) {
  test(`report rejects untrustworthy stage ${value}`, () => assert.throws(() => progress([],value), /timestamp/));
  test(`report excludes untrustworthy completion ${value}`, () => assert.deepEqual(progress([row('bad',{completed_at:value})]).outcomes, []));
}

test('report rejects duplicate identities before selecting facts', () => assert.throws(() => progress([row('a'),row('a')]), /duplicate/));

const scope = {kind:'other',granularity:'action',scope_key:'report-1'};
const decision = (id: string, extra: JsonObject = {}) => row(id,{action_kind:'approve_periodic_report_payload',
  decision_outcome:'reject',decision_scope:scope,bound_agent:'writer',...extra});
const approval = (items: JsonObject[]) => selectPeriodicReportApprovalRetry({
  schema_version:'periodic_report_approval_retry_request_v0',agent_id:'writer',approval_scope:'other:action:report-1',items});

test('approval retry reads the latest real instant and preserves the durable key bytes', () => {
  const result = approval([decision('old',{updated_at:'2026-09-21T18:00:00+08:00'}),
    decision('new',{updated_at:'2026-09-21T11:00:00Z',archive_state:'archive'})]);
  assert.equal(result.revision,createHash('sha256').update('new:2026-09-21T11:00:00Z').digest('hex').slice(0,16));
});

test('approval retry does not authorize other agents, scopes, approvals or malformed time', () => {
  assert.equal(approval([decision('foreign',{bound_agent:'peer'}),decision('scope',{decision_scope:'other'}),
    decision('approve',{decision_outcome:'approve'}),decision('invalid',{updated_at:'invalid'})]).revision,null);
});

test('report selection rejects malformed evaluated state rather than coercing it', () => {
  assert.throws(() => progress([row('a',{actionable:'true'})]),/boolean/);
  assert.throws(() => progress([row('a',{status:'finished'})]),/status/);
});
