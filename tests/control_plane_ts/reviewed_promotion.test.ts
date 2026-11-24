import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, rm, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { qualifiedShadow } from "./local_promotion_fixture.ts";
import { sourceRequest, pendingEntry, settleFiles } from "./shadow_file_fixture.ts";
import { FileAuthorityStore } from "../../loopx/control_plane/coordination/file_authority_store.ts";
import {
  reviewLocalCoordinationAuthorityPromotion,
  executeReviewedCoordinationPromotion,
  LOCAL_COORDINATION_PROMOTION_REVIEW_REQUEST_SCHEMA,
} from "../../loopx/control_plane/coordination/local_authority_runtime.ts";
import { loadLegacyCoordinationWriterFence } from "../../loopx/control_plane/coordination/legacy_writer_fence.ts";
import type { JsonObject } from "../../loopx/control_plane/effect_program.ts";

async function fixture(t: test.TestContext) {
  const root = await mkdtemp(join(tmpdir(), "reviewed-promotion-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const shadow = await qualifiedShadow(root, "hard_lease");
  const projection = { ...shadow.projection, partitions: { todos: null, leases: null } } as JsonObject;
  for (const field of ["capture_lineage_id", "capture_profile", "source_root_digest"])
    delete projection[field];
  const source = await sourceRequest(
    {
      root,
      statePath: join(root, "ACTIVE_GOAL_STATE.md"),
      store: new FileAuthorityStore(join(root, "authority-shadow", "file-v0"), "goal-a"),
      baseline: projection,
    },
    projection,
  );
  const request = {
    ...source,
    schema_version: LOCAL_COORDINATION_PROMOTION_REVIEW_REQUEST_SCHEMA,
    operation_id: "reviewed-promotion",
    minimum_operations: 1,
    required_event_kinds: ["todo_claim"],
    execute: false,
  };
  return { root, request, projection };
}

test("promotion preview exposes an executable exact-plan envelope without fencing", async (t) => {
  const { root, request } = await fixture(t);
  const preview = await reviewLocalCoordinationAuthorityPromotion(request);
  assert.equal(preview.status, "preview_ready");
  const reviewed = (preview.plan as JsonObject).reviewed_plan as JsonObject;
  assert.equal(reviewed?.schema_version, "loopx_reviewed_coordination_promotion_v0");
  assert.equal(reviewed.promotion_plan_sha256, (preview.plan as JsonObject).promotion_plan_sha256);
  assert.equal((await loadLegacyCoordinationWriterFence(root, "goal-a")).status, "missing");
});

test("a changed reviewed plan is rejected before writer fencing or canonical initialization", async (t) => {
  const { root, request } = await fixture(t);
  const result = await reviewLocalCoordinationAuthorityPromotion({
    ...request,
    execute: true,
    expected_promotion_plan_sha256: "0".repeat(64),
  });
  assert.equal(result.status, "not_ready");
  assert.equal(result.reason_code, "local_authority_reviewed_plan_changed");
  assert.equal((await loadLegacyCoordinationWriterFence(root, "goal-a")).status, "missing");
  assert.equal(
    (
      await new FileAuthorityStore(join(root, "authority", "file-v0"), "goal-a", {
        existingOnly: true,
      }).loadAuthority()
    ).status,
    "missing",
  );
});

const operation = (
  root: string,
  plan: JsonObject,
  action: "apply" | "recover",
  execute: boolean,
  source?: JsonObject,
) => ({
  schema_version: "loopx_reviewed_coordination_promotion_operation_v0",
  action,
  runtime_root: root,
  goal_id: "goal-a",
  execute,
  reviewed_plan: plan,
  ...(action === "apply" ? { projection: source!.projection, source_snapshot: source!.source_snapshot } : {}),
});
async function reviewed(request: JsonObject, dependencies = {}) {
  const result = await reviewLocalCoordinationAuthorityPromotion(request, dependencies);
  assert.equal(result.status, "preview_ready", JSON.stringify(result));
  return (result.plan as JsonObject).reviewed_plan as JsonObject;
}

test("reviewed apply uses the saved operation and recovery reads the original receipt after later writes", async (t) => {
  const { root, request } = await fixture(t);
  const plan = await reviewed(request);
  const applied = await executeReviewedCoordinationPromotion(operation(root, plan, "apply", true, request));
  assert.equal(applied.status, "applied", JSON.stringify(applied));
  const store = new FileAuthorityStore(join(root, "authority", "file-v0"), "goal-a");
  const before = await store.loadAuthority();
  assert.equal(before.status, "loaded");
  if (before.status !== "loaded") return;
  const later = await store.commitAuthority({
    operation_id: "later-canonical-operation",
    expected_provider_revision: before.provider_revision,
    next_projection: before.head,
    events: [],
    receipts: [{ kind: "later" }],
  });
  assert.equal(later.status, "applied");
  await rm(join(root, "ACTIVE_GOAL_STATE.md"));
  const head = await store.loadAuthority();
  for (const execute of [false, true]) {
    const replay = await executeReviewedCoordinationPromotion(operation(root, plan, "recover", execute));
    assert.equal(replay.status, "replayed", JSON.stringify(replay));
    assert.equal(replay.provider_revision, applied.provider_revision);
    assert.equal(replay.cursor, "1");
    assert.equal(replay.executed, false);
    assert.deepEqual(await store.loadAuthority(), head);
  }
});

test("a source change between review and execution rejects the old plan without freezing the Goal", async (t) => {
  const { root, request, projection } = await fixture(t);
  const plan = await reviewed(request);
  const f = {
    root,
    statePath: join(root, "ACTIVE_GOAL_STATE.md"),
    baseline: projection,
    store: new FileAuthorityStore(join(root, "authority-shadow", "file-v0"), "goal-a"),
  };
  const { commitLocalAuthorityShadowEntry } = await import(
    "../../loopx/control_plane/coordination/local_authority_shadow.ts"
  );
  const rows = structuredClone(projection.todos) as JsonObject[];
  rows[0].text = "A newer independently committed objective";
  const entry = await pendingEntry(
    f,
    2,
    { handoff_mode: "hard_lease", todos: rows },
    { writeClass: "todo_update" },
  );
  const committed = await commitLocalAuthorityShadowEntry(entry);
  assert.equal(committed.outcome, "delivered");
  await settleFiles(f, entry, committed);
  const fresh: JsonObject = { ...projection, todos: rows };
  const { coordinationTodoReadModel } = await import(
    "../../loopx/control_plane/coordination/coordination_projection.ts"
  );
  fresh.todo_read_model = coordinationTodoReadModel(
    rows,
    (projection.todo_read_model as JsonObject).schema_version,
  );
  const observation = await sourceRequest(f, fresh);
  const before = await readFile(f.statePath);
  const rejected = await executeReviewedCoordinationPromotion(
    operation(root, plan, "apply", true, observation),
  );
  assert.equal(rejected.reason_code, "local_authority_reviewed_plan_changed", JSON.stringify(rejected));
  assert.equal((await loadLegacyCoordinationWriterFence(root, "goal-a")).status, "missing");
  assert.deepEqual(await readFile(f.statePath), before);
});

test("recovery is effect-free until execute and cannot create a missing writer fence", async (t) => {
  const { root, request } = await fixture(t);
  const plan = await reviewed(request);
  for (const execute of [false, true]) {
    const rejected = await executeReviewedCoordinationPromotion(operation(root, plan, "recover", execute));
    assert.equal(rejected.reason_code, "local_authority_writer_fence_not_verified");
    assert.equal((await loadLegacyCoordinationWriterFence(root, "goal-a")).status, "missing");
  }
});

test("a fence-to-commit interruption recovers with no legacy document and no new review identity", async (t) => {
  const { root, request } = await fixture(t);
  class InterruptOnce extends FileAuthorityStore {
    interrupt = true;
    override async commitAuthority(
      value: import("../../loopx/control_plane/coordination/authority_store.ts").AuthorityStoreCommit,
    ) {
      if (this.interrupt) {
        this.interrupt = false;
        throw new Error("process stopped before commit");
      }
      return super.commitAuthority(value);
    }
  }
  const store = new InterruptOnce(join(root, "authority", "file-v0"), "goal-a");
  const deps = { createCanonicalStore: () => store };
  const plan = await reviewed(request, deps);
  const failed = await executeReviewedCoordinationPromotion(
    operation(root, plan, "apply", true, request),
    deps,
  );
  assert.equal(failed.status, "failed");
  assert.equal(failed.legacy_writer_fenced, true);
  assert.equal((await store.loadAuthority()).status, "missing");
  await rm(join(root, "ACTIVE_GOAL_STATE.md"));
  const preview = await executeReviewedCoordinationPromotion(operation(root, plan, "recover", false), deps);
  assert.equal(preview.status, "recovery_ready", JSON.stringify(preview));
  assert.equal(preview.executed, false);
  assert.equal((await store.loadAuthority()).status, "missing");
  const recovered = await executeReviewedCoordinationPromotion(operation(root, plan, "recover", true), deps);
  assert.equal(recovered.status, "applied", JSON.stringify(recovered));
  assert.equal(recovered.operation_id, request.operation_id);
});

test("a thrown acknowledgement after a successful commit is resolved by durable receipt readback", async (t) => {
  const { root, request } = await fixture(t);
  class LoseResponse extends FileAuthorityStore {
    writes = 0;
    override async commitAuthority(
      value: import("../../loopx/control_plane/coordination/authority_store.ts").AuthorityStoreCommit,
    ): Promise<never> {
      this.writes++;
      await super.commitAuthority(value);
      throw new Error("response lost after durable commit");
    }
  }
  const store = new LoseResponse(join(root, "authority", "file-v0"), "goal-a");
  const deps = { createCanonicalStore: () => store };
  const plan = await reviewed(request, deps);
  const recovered = await executeReviewedCoordinationPromotion(
    operation(root, plan, "apply", true, request),
    deps,
  );
  assert.equal(recovered.status, "recovered", JSON.stringify(recovered));
  assert.equal(store.writes, 1);
  const replay = await executeReviewedCoordinationPromotion(operation(root, plan, "recover", true), deps);
  assert.equal(replay.status, "replayed");
  assert.equal(store.writes, 1);
});

for (const mutation of [
  "goal",
  "runtime",
  "digest",
  "policy",
  "source",
  "operation",
  "embedded_execute",
  "unknown_envelope",
] as const) {
  test(`review carrier rejects changed ${mutation} before any provider opens`, async (t) => {
    const { root, request } = await fixture(t);
    const plan = await reviewed(request);
    const changed = structuredClone(plan);
    const row = changed.request as JsonObject;
    if (mutation === "goal") row.goal_id = "other";
    if (mutation === "runtime") row.runtime_root = root + "-other";
    if (mutation === "digest") changed.promotion_plan_sha256 = "f".repeat(64);
    if (mutation === "policy") row.minimum_operations = 2;
    if (mutation === "source") row.expected_shadow_projection_sha256 = "f".repeat(64);
    if (mutation === "operation") row.operation_id = "another-operation";
    if (mutation === "embedded_execute") row.execute = true;
    if (mutation === "unknown_envelope") changed.allow_unqualified = true;
    let opens = 0;
    const result = await executeReviewedCoordinationPromotion(operation(root, changed, "recover", true), {
      createCanonicalStore: () => {
        opens++;
        throw new Error("must reject before opening");
      },
    });
    assert.equal(result.reason_code, "invalid_reviewed_promotion_plan");
    assert.equal(opens, 0);
    assert.equal((await loadLegacyCoordinationWriterFence(root, "goal-a")).status, "missing");
  });
}

test("the unmodified CLI preview envelope is accepted and cross-Goal wrappers are rejected", async (t) => {
  const { root, request } = await fixture(t);
  const preview = await reviewLocalCoordinationAuthorityPromotion(request);
  const cli = {
    schema_version: "loopx_coordination_shadow_admin_v0",
    action: "promote",
    ok: true,
    goal_id: "goal-a",
    promotion: preview,
  };
  const result = await executeReviewedCoordinationPromotion(operation(root, cli, "apply", false, request));
  assert.equal(result.status, "preview_ready");
  const rejected = await executeReviewedCoordinationPromotion(
    operation(root, { ...cli, goal_id: "other" }, "apply", true, request),
  );
  assert.equal(rejected.reason_code, "invalid_reviewed_promotion_plan");
});


test("registry removal rejects a captured preview before fencing", async (t) => {
  const {root, request} = await fixture(t);
  await rm(join(root, "registry.json"));
  const result = await reviewLocalCoordinationAuthorityPromotion({...request, execute: true});
  assert.equal(result.reason_code, "source_registry_changed_retry");
  assert.equal(result.legacy_writer_fenced, false);
  assert.equal((await loadLegacyCoordinationWriterFence(root, "goal-a")).status, "missing");
});

test("saved plan cannot carry old registrations through a fresh source snapshot", async (t) => {
  const {root, request} = await fixture(t);
  const explicit = {...request, handoff_mode_migration: "preserve", registered_agents: ["agent-a", "agent-b"]};
  const plan = await reviewed(explicit);
  await writeFile(join(root, "registry.json"), JSON.stringify({goals: [{id: "goal-a", coordination: {registered_agents: ["agent-a"]}}]}));
  const snapshot = (request as JsonObject).source_snapshot as JsonObject;
  const {createHash} = await import("node:crypto");
  const current = {...snapshot, registry_source: {path: join(root, "registry.json"), registered_agents: ["agent-a"],
    sha256: createHash("sha256").update(await readFile(join(root, "registry.json"))).digest("hex")}};
  const result = await executeReviewedCoordinationPromotion(operation(root, plan, "apply", true,
    {...request, source_snapshot: current}));
  assert.equal(result.reason_code, "promotion_registration_changed_retry");
  assert.equal((await loadLegacyCoordinationWriterFence(root, "goal-a")).status, "missing");
});

test("registry exclusion spans canonical commit and releases after success", async (t) => {
  const {root, request} = await fixture(t);
  const {withFileMutationLock} = await import("../../loopx/control_plane/effect_runtime_io.ts");
  const {EffectRuntimeLockTimeoutError} = await import("../../loopx/control_plane/effect_runtime_errors.ts");
  class RegistryCheckingStore extends FileAuthorityStore {
    override async commitAuthority(input: Parameters<FileAuthorityStore["commitAuthority"]>[0]) {
      await assert.rejects(withFileMutationLock(join(root, "registry.json"), async () => {}, 0), EffectRuntimeLockTimeoutError);
      return await super.commitAuthority(input);
    }
  }
  const store = new RegistryCheckingStore(join(root, "authority", "file-v0"), "goal-a");
  const result = await reviewLocalCoordinationAuthorityPromotion({...request, execute: true}, {createCanonicalStore: () => store});
  assert.equal(result.status, "applied", JSON.stringify(result));
  await withFileMutationLock(join(root, "registry.json"), async () => {}, 0);
});

test("stale source reports an existing fence and saved recovery needs no legacy registry", async (t) => {
  const {root, request} = await fixture(t);
  const plan = await reviewed(request);
  const result = await executeReviewedCoordinationPromotion(operation(root, plan, "apply", true, request));
  assert.equal(result.status, "applied");
  await rm(join(root, "registry.json"));
  const stale = await reviewLocalCoordinationAuthorityPromotion({...request, execute: true});
  assert.equal(stale.reason_code, "source_registry_changed_retry");
  assert.equal(stale.legacy_writer_fenced, true);
  const replay = await executeReviewedCoordinationPromotion(operation(root, plan, "recover", true));
  assert.equal(replay.status, "replayed", JSON.stringify(replay));
  assert.equal(replay.executed, false);
});


for (const strategy of ["preserve", "hard_lease"] as const) {
  test(`saved reviewed apply preserves the explicit ${strategy} policy`, async (t) => {
    const {root, request} = await fixture(t);
    const explicit = {...request, handoff_mode_migration: strategy, registered_agents: ["agent-a", "agent-b"]};
    const plan = await reviewed(explicit);
    const result = await executeReviewedCoordinationPromotion(operation(root, plan, "apply", true, request));
    assert.equal(result.status, "applied", JSON.stringify(result));
    const replay = await executeReviewedCoordinationPromotion(operation(root, plan, "recover", true));
    assert.equal(replay.status, "replayed");
  });
}

for (const rejection of ["qualification", "plan", "migration"] as const) {
  test(`failed ${rejection} admission observes the existing promotion fence`, async (t) => {
    const {root, request} = await fixture(t);
    assert.equal((await reviewLocalCoordinationAuthorityPromotion({...request, execute: true})).status, "applied");
    const changed = rejection === "qualification" ? {minimum_operations: 10000}
      : rejection === "plan" ? {expected_promotion_plan_sha256: "0".repeat(64)}
      : {handoff_mode_migration: "hard_lease", registered_agents: []};
    const result = await reviewLocalCoordinationAuthorityPromotion({...request, ...changed});
    assert.equal(result.status, "not_ready", JSON.stringify(result));
    assert.equal(result.legacy_writer_fenced, true);
    assert.equal(result.executed, false);
    assert.equal((await loadLegacyCoordinationWriterFence(root, "goal-a")).status, "loaded");
  });
}

test("a downstream timeout is not mislabeled as registry contention", async (t) => {
  const {request} = await fixture(t);
  const {withShadowRegistrySource} = await import("../../loopx/control_plane/coordination/shadow_registry_source.ts");
  const {EffectRuntimeLockTimeoutError} = await import("../../loopx/control_plane/effect_runtime_errors.ts");
  const downstream = new EffectRuntimeLockTimeoutError("canonical store lock timed out");
  await assert.rejects(withShadowRegistrySource((request as JsonObject).source_snapshot as JsonObject, async () => {
    throw downstream;
  }), (error) => error === downstream);
});
