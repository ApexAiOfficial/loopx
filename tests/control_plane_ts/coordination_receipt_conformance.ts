/** Transport faults never replace the real provider's successful writes. */
import assert from "node:assert/strict";
import test from "node:test";
import type {JsonObject} from "../../loopx/control_plane/effect_program.ts";
import type {AuthorityStore, AuthorityStoreCommitResult} from "../../loopx/control_plane/coordination/authority_store.ts";
import {canonicalAuthoritySha256} from "../../loopx/control_plane/coordination/authority_store_codec.ts";
import type {AuthorityStoreConformanceFactory} from "./authority_store_conformance.ts";
import {coordinationCommandFixture, type Command} from "./coordination_command_fixture.ts";

const commands: readonly Command[] = ["create", "claim", "update", "complete", "supersede", "archive", "monitor"];
type Fault = "none" | "lost_response" | "unreadable_receipt" | "ambiguous_unreadable" | "thrown_response";
const faults: readonly Fault[] = ["none", "lost_response", "unreadable_receipt", "ambiguous_unreadable", "thrown_response"];


export function registerCoordinationReceiptConformance(provider: string, factory: AuthorityStoreConformanceFactory) {
  for (const command of commands) for (const fault of faults) {
    test(`${provider}: ${command} receipt recovery / ${fault}`, async t => {
      const {store} = await factory(t);
      const {invoke, operation_id, initial} = await coordinationCommandFixture(store, command);
      let attempted = false, commits = 0;
      const wrapped: AuthorityStore = {
        storeIdentity: () => store.storeIdentity(), loadAuthority: () => store.loadAuthority(),
        scanCommitted: (cursor, limit) => store.scanCommitted(cursor, limit),
        readReceipt: id => attempted && (fault === "unreadable_receipt" || fault === "ambiguous_unreadable")
          ? Promise.resolve({status: "unavailable", reason_code: "synthetic_disconnect", reason: "receipt transport disconnected"})
          : store.readReceipt(id),
        commitAuthority: async commit => {
          commits++; attempted = true;
          const result = await store.commitAuthority(commit);
          assert.equal(result.status, "applied", JSON.stringify(result));
          if (fault === "thrown_response") throw new Error("synthetic response lost after commit");
          return (fault === "lost_response" || fault === "ambiguous_unreadable")
            ? {status: "ambiguous", reason_code: "synthetic_timeout", reason: "commit response lost"} satisfies AuthorityStoreCommitResult
            : result;
        },
      };
      const result = await invoke(wrapped);
      const uncertain = fault === "unreadable_receipt" || fault === "ambiguous_unreadable";
      assert.equal(result.status, uncertain ? "ambiguous" : fault === "none" ? "applied" : "recovered", JSON.stringify(result));
      if (uncertain) {
        assert.equal((result.recovery as JsonObject).operation_id, operation_id);
        assert.equal((result.recovery as JsonObject).retry_with_same_operation_id, true);
        assert.equal(result.changed, false);
      }
      assert.equal(commits, 1, "a response fault never triggers a second commit");
      const after = await store.loadAuthority();
      assert.notDeepEqual(after, initial);
      const receipt = await store.readReceipt(operation_id);
      assert.equal(receipt.status, "found");
      assert.equal((await invoke(store)).status, "replayed");
      assert.deepEqual(await store.loadAuthority(), after, "retry never changes head, leases or successors");
      // An unrelated later transaction must not redirect recovery to the latest head.
      assert.equal(after.status, "loaded");
      if (after.status !== "loaded" || receipt.status !== "found") return;
      await store.commitAuthority({operation_id: "later-write", expected_provider_revision: after.provider_revision,
        next_projection: after.head, events: [], receipts: []});
      const replay = await invoke(store);
      assert.equal(replay.cursor, receipt.cursor);
      assert.equal(replay.provider_revision, receipt.provider_revision);
      assert.equal(canonicalAuthoritySha256(replay.original_receipt ?? (replay.writeback as JsonObject)),
        canonicalAuthoritySha256(result.original_receipt ?? replay.original_receipt ?? replay.writeback));
    });
  }
}
