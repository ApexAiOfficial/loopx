/** Same typed capability plan and existing native effects on every real store. */
import assert from "node:assert/strict";
import {test} from "node:test";
import type {JsonObject} from "../../loopx/control_plane/effect_program.ts";
import {planIssueFixMonitorReconciliation, ISSUE_FIX_MONITOR_PLAN_REQUEST} from "../../loopx/control_plane/capabilities/issue_fix_monitor_reconciliation.ts";
import {executeCoordinationTodoUpdate} from "../../loopx/control_plane/coordination/todo_update.ts";
import {executeCanonicalTaskLeaseAcquire} from "../../loopx/control_plane/coordination/task_lease_acquire.ts";
import {executeCanonicalTaskLeaseLifecycle} from "../../loopx/control_plane/coordination/task_lease_lifecycle.ts";
import {executeCoordinationTodoTerminalLifecycle} from "../../loopx/control_plane/coordination/todo_terminal_lifecycle.ts";
import {indexCoordinationProjection} from "../../loopx/control_plane/coordination/coordination_projection.ts";
import {productionScaleGroupedMonitorFixture} from "./production_scale_coordination_fixture.ts";
import type {AuthorityStoreConformanceFactory} from "./authority_store_conformance.ts";

export function registerIssueFixMonitorReconciliationConformance(provider: string, factory: AuthorityStoreConformanceFactory) {
  for (const schema of ["native", "legacy"] as const) {
    test(`${provider}: grouped Monitor plan executes observation, stop and next cycle in the full ${schema} graph`, async t => {
      const {store} = await factory(t);
      const f = productionScaleGroupedMonitorFixture("grouped-monitor", schema);
      assert.equal((await store.commitAuthority({operation_id: "seed", expected_provider_revision: null,
        events: [], receipts: [], next_projection: f.projection})).status, "applied");
      const loaded = async () => {
        const result = await store.loadAuthority();
        assert.equal(result.status, "loaded");
        if (result.status !== "loaded") throw new Error("missing fixture authority");
        return result;
      };
      const before = (await loaded()).head;
      const ledger = [{grouped_monitor_projection: {materialize_nonempty_bucket_monitor: true,
        target_key: f.targetKey, member_key: "example/repo#1", action_kind: "issue_fix_pr_state_checks_pending",
        state_bucket: "checks_pending", repository: "example/repo"}}];
      const plan = async (empty = false, now = f.now) => planIssueFixMonitorReconciliation({
        schema_version: ISSUE_FIX_MONITOR_PLAN_REQUEST, ledger_rows: empty ? [] : ledger,
        todos: [...indexCoordinationProjection((await loaded()).head, "grouped-monitor").todos.values()],
        cadence: "30m", generated_at: now.toISOString()}).steps as JsonObject[];
      const acquire = (key: string) => executeCanonicalTaskLeaseAcquire(store, {
        goal_id: "grouped-monitor", todo_id: f.target, owner: f.actor, idempotency_key: key,
        expected_version: null, ttl_seconds: 60, write_scopes: [], registered_agents: f.registered_agents, now: f.now});
      const first = (await plan())[0];
      assert.equal(first.operation, "observe");
      const acquired = await acquire("group-observation");
      assert.equal(acquired.status, "applied", JSON.stringify(acquired));
      const lease = acquired.lease as JsonObject;
      const update = {goal_id: "grouped-monitor", todo_id: f.target, expected_role: "agent", actor_agent_id: f.actor,
        registered_agents: f.registered_agents, operation_id: "group-observation", patch: {}, clear_fields: [],
        planning_intent: {reason: first.reason}, monitor_observation: first.observation as {generated_at: string; result_hash: string; material_change: boolean},
        lease_idempotency_key: String(lease.idempotency_key), lease_expected_version: Number(lease.version),
        dry_run: false, now: f.now};
      assert.equal((await executeCoordinationTodoUpdate(store, update)).status, "applied");
      assert.equal((await executeCoordinationTodoUpdate(store, update)).status, "replayed");
      assert.equal((await plan())[0].operation, "unchanged");
      assert.equal((await executeCanonicalTaskLeaseLifecycle(store, {
        goal_id: "grouped-monitor", todo_id: f.target, operation: "release", owner: f.actor,
        idempotency_key: String(lease.idempotency_key), expected_version: Number(lease.version), ttl_seconds: null,
        new_owner: null, new_idempotency_key: null, registered_agents: f.registered_agents, now: f.now,
      })).status, "applied");
      const completionLease = await acquire("group-stop");
      assert.equal(completionLease.status, "applied");
      const proof = completionLease.lease as JsonObject;
      const stop = (await plan(true))[0];
      assert.equal(stop.operation, "complete");
      const terminal = {goal_id: "grouped-monitor", todo_id: f.target, expected_role: "agent" as const,
        command: "complete" as const, actor_agent_id: f.actor, registered_agents: f.registered_agents,
        lifecycle_grants: [], authority_reason: null, decision_outcome: null, operation_identity: {kind: "explicit" as const, operation_id: "group-stop"},
        lease_idempotency_key: String(proof.idempotency_key), lease_expected_version: Number(proof.version),
        allow_user_gate_auto_acquire: false, requested_no_followup: true, requested_completion_turn_key: null,
        requested_completion_identity_source: null, linked_successor_todo_ids: [], successor_intents: [],
        note: null, evidence: String(stop.evidence), reason: null, clear_claim: false,
        validation_declaration: null, validation_receipt: null, completion_policy_request: null, dry_run: false, now: f.now};
      assert.equal((await executeCoordinationTodoTerminalLifecycle(store, terminal)).status, "applied");
      assert.equal((await executeCoordinationTodoTerminalLifecycle(store, terminal)).status, "replayed");
      const nextTime = new Date(f.now.valueOf() + 1000);
      const reopen = (await plan(false, nextTime))[0];
      assert.equal(reopen.operation, "reactivate");
      assert.equal((await executeCoordinationTodoUpdate(store, {...update, operation_id: "group-reopen",
        lease_idempotency_key: null, lease_expected_version: null, planning_intent: {status: "open", no_followup: false},
        monitor_observation: reopen.observation as typeof update.monitor_observation, now: nextTime})).status, "applied");
      const after = (await loaded()).head;
      const target = indexCoordinationProjection(after, "grouped-monitor").todos.get(f.target)!;
      assert.equal(target.status, "open");
      assert.equal(target.material_change_generation, 6);
      assert.deepEqual((after.todos as JsonObject[]).filter(row => row.todo_id !== f.target),
        (before.todos as JsonObject[]).filter(row => row.todo_id !== f.target));
      assert.deepEqual((after.leases as JsonObject[]).filter(row => row.todo_id !== f.target), before.leases);
    });
  }
}
