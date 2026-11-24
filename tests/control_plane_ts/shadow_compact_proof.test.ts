import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { JsonObject } from "../../loopx/control_plane/effect_program.ts";
import { coordinationTodoReadModel } from "../../loopx/control_plane/coordination/coordination_projection.ts";
import { readLocalAuthorityShadow } from "../../loopx/control_plane/coordination/local_authority_shadow.ts";
import { LOCAL_AUTHORITY_SHADOW_READ_REQUEST_SCHEMA } from "../../loopx/control_plane/coordination/coordination_state_contract.generated.ts";
import { productionScaleCoordinationFixture } from "./production_scale_coordination_fixture.ts";
import { qualifiedPromotionSource } from "./promotion_recovery_conformance.ts";

for (const shape of ["native", "legacy"] as const) {
  test(`compact shadow proof keeps full lineage decisions below the RPC response budget (${shape})`, async (t) => {
    const root = await mkdtemp(join(tmpdir(), "compact-shadow-proof-"));
    t.after(() => rm(root, { recursive: true, force: true }));
    const fixture = productionScaleCoordinationFixture("goal-a", shape);
    const rows = fixture.projection.todos as JsonObject[];
    // Broad retained records reproduce repeated-projection transport pressure.
    // No population, history or stored metadata is removed to meet the budget.
    for (const row of rows) row.note = "Retained public fixture metadata. ".repeat(35);
    fixture.projection.todo_read_model = coordinationTodoReadModel(
      rows,
      (fixture.projection.todo_read_model as JsonObject).schema_version as string,
    );
    const source = await qualifiedPromotionSource(root, fixture.projection);
    const request = {
      schema_version: LOCAL_AUTHORITY_SHADOW_READ_REQUEST_SCHEMA,
      runtime_root: root,
      goal_id: "goal-a",
      scan_limit: 10000,
    };
    const full = await readLocalAuthorityShadow(request);
    const compact = await readLocalAuthorityShadow({ ...request, read_model: "proof" });
    assert.equal(full.status, "loaded");
    assert.equal(compact.status, "loaded");
    assert.ok(
      Buffer.byteLength(JSON.stringify(full)) > 2 * 1024 * 1024,
      "the former full response must actually reproduce the 2 MiB transport failure",
    );
    assert.ok(Buffer.byteLength(JSON.stringify(compact)) < 128 * 1024);
    assert.equal(compact.head, null);
    assert.equal(compact.scan, null, "do not return a second copy of the same transaction proof");
    for (const key of ["provider_revision", "cursor", "store_identity", "head_digest", "partitions"]) {
      assert.deepEqual(compact[key], full[key]);
    }
    const fullProof = full.proof as JsonObject;
    const proof = compact.proof as JsonObject;
    for (const key of [
      "capture_lineage_id",
      "bootstrap_provider_revision",
      "last_sequences",
      "last_applied_sequences",
    ]) {
      assert.deepEqual(proof[key], fullProof[key]);
    }
    const original = fullProof.transactions as JsonObject[];
    const transactions = proof.transactions as JsonObject[];
    assert.equal(transactions.length, original.length);
    for (let i = 0; i < transactions.length; i++) {
      for (const key of ["cursor", "provider_revision", "operation_id", "receipts"]) {
        assert.deepEqual(transactions[i][key], original[i][key]);
      }
      assert.deepEqual(
        transactions[i].projection_partitions,
        (original[i].projection as JsonObject).partitions,
      );
      assert.equal("projection" in transactions[i], false);
    }
    const progress = await readLocalAuthorityShadow({ ...request, read_model: "proof", scan_limit: 0 });
    assert.deepEqual((progress.proof as JsonObject).transactions, []);
    assert.deepEqual((progress.proof as JsonObject).last_sequences, { todos: 1, leases: 0 });
    const receipt = await readLocalAuthorityShadow({
      ...request,
      read_model: "proof",
      scan_limit: 0,
      receipt_operation_id: transactions[1].operation_id,
    });
    assert.deepEqual((receipt.proof as JsonObject).receipt, transactions[1]);
    assert.deepEqual((await source.store.loadAuthority()).status, "loaded");
    await assert.rejects(readLocalAuthorityShadow({ ...request, read_model: "unchecked" }), /read_model/);
  });
}
