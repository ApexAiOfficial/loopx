import { LOCAL_AUTHORITY_SHADOW_TRANSACTION_PROJECTION_SCHEMA } from "../../loopx/control_plane/coordination/coordination_state_contract.generated.ts";
import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, mkdir, rm, writeFile, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { JsonObject } from "../../loopx/control_plane/effect_program.ts";
import type { AuthorityStoreConformanceFactory } from "./authority_store_conformance.ts";
import { authorityStoreSourceAuthority } from "../../loopx/control_plane/coordination/authority_store.ts";
import { FileAuthorityStore } from "../../loopx/control_plane/coordination/file_authority_store.ts";
import {
  bootstrapCoordinationRuntimeShadow,
  COORDINATION_RUNTIME_SHADOW_BOOTSTRAP_REQUEST_SCHEMA,
} from "../../loopx/control_plane/coordination/runtime_shadow.ts";
import {
  reviewLocalCoordinationAuthorityPromotion,
  executeReviewedCoordinationPromotion,
  LOCAL_COORDINATION_PROMOTION_REVIEW_REQUEST_SCHEMA,
} from "../../loopx/control_plane/coordination/local_authority_runtime.ts";
import {deliverShadowEntry} from "../../loopx/control_plane/coordination/shadow_entry_delivery.ts";
import {entrySelection} from "./shadow_file_fixture.ts";
import { canonicalAuthoritySha256 } from "../../loopx/control_plane/coordination/authority_store_codec.ts";
import { loadLegacyCoordinationWriterFence } from "../../loopx/control_plane/coordination/legacy_writer_fence.ts";
import { productionScaleCoordinationFixture } from "./production_scale_coordination_fixture.ts";
import { sourceRequest, pendingEntry, settleFiles } from "./shadow_file_fixture.ts";

/** Full retained Todo/lease population, then one actual outbox transaction.
 * State bytes are fixture transport; no real Goal or implicit promotion is used. */
export async function qualifiedPromotionSource(root: string, input: JsonObject) {
  const projection: JsonObject = {
    ...input,
    schema_version: LOCAL_AUTHORITY_SHADOW_TRANSACTION_PROJECTION_SCHEMA,
    source_authority: "legacy_markdown_and_task_lease",
    partitions: { todos: null, leases: null },
  };
  const statePath = join(root, "ACTIVE_GOAL_STATE.md");
  await writeFile(statePath, "---\ngoal_id: goal-a\nhandoff_mode: hard_lease\n---\n\n## Agent Todo\n\n");
  const store = new FileAuthorityStore(join(root, "authority-shadow", "file-v0"), "goal-a");
  const leaseDirectory = join(root, "goals", "goal-a", "task-leases");
  await mkdir(leaseDirectory, { recursive: true });
  for (const lease of projection.leases as JsonObject[]) {
    await writeFile(join(leaseDirectory, `${lease.todo_id}.json`), JSON.stringify(lease));
  }
  const fixture = { root, statePath, store, baseline: projection };
  const bootstrapped = await bootstrapCoordinationRuntimeShadow({
    ...(await sourceRequest(fixture, projection)),
    schema_version: COORDINATION_RUNTIME_SHADOW_BOOTSTRAP_REQUEST_SCHEMA,
    operation_id: "bootstrap:full-source",
    source_version: "full-source:0",
  });
  assert.equal(bootstrapped.status, "applied", JSON.stringify(bootstrapped));
  const todos = structuredClone(projection.todos) as JsonObject[];
  todos[0].note = "A verified source mutation precedes the migration review";
  const entry = await pendingEntry(
    fixture,
    1,
    { handoff_mode: "hard_lease", todos },
    { writeClass: "todo_update" },
  );
  const mirrored = await deliverShadowEntry(entrySelection(entry));
  assert.equal(mirrored.outcome, "delivered", JSON.stringify(mirrored));
  await settleFiles(fixture, entry, mirrored);
  const loaded = await store.loadAuthority();
  assert.equal(loaded.status, "loaded");
  if (loaded.status !== "loaded") throw new Error("qualified source missing");
  const source: JsonObject = { ...loaded.head, partitions: { todos: null, leases: null } };
  for (const field of ["capture_lineage_id", "capture_profile", "source_root_digest"]) delete source[field];
  const request: JsonObject = {
    ...(await sourceRequest(fixture, source)),
    schema_version: LOCAL_COORDINATION_PROMOTION_REVIEW_REQUEST_SCHEMA,
    operation_id: "promote:full-source",
    minimum_operations: 1,
    required_event_kinds: ["todo_update"],
    execute: false,
  };
  return { statePath, store, head: loaded.head, request };
}

export function registerPromotionRecoveryConformance(
  name: string,
  factory: AuthorityStoreConformanceFactory,
): void {
  for (const schema of ["native", "legacy"] as const) {
    test(`${name}: reviewed full-source migration and recovery retain exact history (${schema})`, async (context) => {
      const { store, contender } = await factory(context);
      const root = await mkdtemp(join(tmpdir(), "promotion-full-source-"));
      context.after(() => rm(root, { recursive: true, force: true }));
      const fixture = productionScaleCoordinationFixture("goal-a", schema);
      const source = await qualifiedPromotionSource(root, fixture.projection);
      const dependencies = { createCanonicalStore: () => store };
      const preview = await reviewLocalCoordinationAuthorityPromotion(source.request, dependencies);
      assert.equal(preview.status, "preview_ready", JSON.stringify(preview));
      const envelope = (preview.plan as JsonObject).reviewed_plan as JsonObject;
      const operation = {
        schema_version: "loopx_reviewed_coordination_promotion_operation_v0",
        runtime_root: root,
        goal_id: "goal-a",
        reviewed_plan: envelope,
      };
      const registryPath = join(root, "registry.json");
      const originalRegistry = await readFile(registryPath);
      await writeFile(registryPath, JSON.stringify({goals: []}));
      const stale = await executeReviewedCoordinationPromotion({
        ...operation, action: "apply", execute: true,
        projection: source.request.projection, source_snapshot: source.request.source_snapshot,
      }, dependencies);
      assert.equal(stale.reason_code, "source_registry_changed_retry");
      assert.equal(stale.legacy_writer_fenced, false);
      assert.equal((await store.loadAuthority()).status, "missing");
      assert.equal((await loadLegacyCoordinationWriterFence(root, "goal-a")).status, "missing");
      await writeFile(registryPath, originalRegistry);
      const applied = await executeReviewedCoordinationPromotion(
        {
          ...operation,
          action: "apply",
          execute: true,
          projection: source.request.projection,
          source_snapshot: source.request.source_snapshot,
        },
        dependencies,
      );
      assert.equal(applied.status, "applied", JSON.stringify(applied));
      assert.equal(applied.canonical_authority, authorityStoreSourceAuthority(store));
      const promoted = await contender.loadAuthority();
      assert.equal(promoted.status, "loaded");
      if (promoted.status !== "loaded") return;
      assert.deepEqual(
        promoted.head,
        source.head,
        "migration cannot drop unknown metadata, claims, standing decisions or leases",
      );
      assert.equal((promoted.head.todos as unknown[]).length, fixture.expected_initial_todo_count);
      assert.equal((promoted.head.leases as unknown[]).length, fixture.expected_current_lease_count);
      const receipt = await contender.readReceipt(String(applied.operation_id));
      assert.equal(receipt.status, "found");
      // A later writer advances canonical state. Recovery must prove transaction one,
      // without replacing later work or interpreting a current revision as its receipt.
      const later = { ...promoted.head, recovery_conformance_marker: "later-independent-write" };
      const changed = await contender.commitAuthority({
        expected_provider_revision: promoted.provider_revision,
        operation_id: "after-promotion",
        next_projection: later,
        events: [],
        receipts: [],
      });
      assert.equal(changed.status, "applied");
      await rm(source.statePath);
      await rm(registryPath);
      const head = await store.loadAuthority();
      const fence = await loadLegacyCoordinationWriterFence(root, "goal-a");
      for (const execute of [false, true]) {
        const recovered = await executeReviewedCoordinationPromotion(
          { ...operation, action: "recover", execute },
          dependencies,
        );
        assert.equal(recovered.status, "replayed", JSON.stringify(recovered));
        assert.equal(recovered.provider_revision, applied.provider_revision);
        assert.equal(recovered.cursor, "1");
        assert.equal(recovered.executed, false);
        assert.deepEqual(await store.loadAuthority(), head);
        assert.deepEqual(await store.readReceipt(String(applied.operation_id)), receipt);
        assert.deepEqual(await loadLegacyCoordinationWriterFence(root, "goal-a"), fence);
      }
      const altered = structuredClone(envelope);
      (altered.request as JsonObject).minimum_operations = 2;
      const invalid = await executeReviewedCoordinationPromotion(
        { ...operation, reviewed_plan: altered, action: "recover", execute: true },
        dependencies,
      );
      assert.equal(invalid.reason_code, "invalid_reviewed_promotion_plan");
      assert.deepEqual(await store.loadAuthority(), head);
      assert.notEqual(canonicalAuthoritySha256(later), canonicalAuthoritySha256(source.head));
    });
  }
}
