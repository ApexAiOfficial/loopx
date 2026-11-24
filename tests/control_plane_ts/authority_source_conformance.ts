import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import {mkdtemp, rm, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import test from "node:test";
import type {AuthorityStore} from "../../loopx/control_plane/coordination/authority_store.ts";
import {registryAuthoritySourceCheck} from "../../loopx/control_plane/coordination/authority_source.ts";
import type {AuthorityStoreConformanceFactory} from "./authority_store_conformance.ts";
import {coordinationCommandFixture, type Command} from "./coordination_command_fixture.ts";

const commands: readonly Command[] = ["create", "claim", "update", "complete", "supersede", "monitor"];

async function sourceFixture(t: test.TestContext) {
  const root = await mkdtemp(join(tmpdir(), "loopx-source-"));
  t.after(() => rm(root, {recursive: true, force: true}));
  const path = join(root, "registry.json");
  const body = JSON.stringify({registered_agents: ["agent-a", "agent-b"]});
  const restore = () => writeFile(path, body);
  await restore();
  const check = registryAuthoritySourceCheck({registry_source: {
    path, sha256: createHash("sha256").update(body).digest("hex"),
  }}, true);
  return {check, restore, revoke: () => writeFile(path, "{}"), remove: () => rm(path)};
}

/** Only schedule a real registry edit after the real backend read. No mocked
 * head, receipt or successful commit supplies the invariant being asserted. */
function afterLoad(store: AuthorityStore, change: () => Promise<void>): AuthorityStore {
  return {
    storeIdentity: () => store.storeIdentity(),
    loadAuthority: async () => {const head = await store.loadAuthority(); await change(); return head;},
    readReceipt: id => store.readReceipt(id),
    scanCommitted: (cursor, limit) => store.scanCommitted(cursor, limit),
    commitAuthority: commit => store.commitAuthority(commit),
  };
}

export function registerAuthoritySourceConformance(provider: string, factory: AuthorityStoreConformanceFactory) {
  for (const command of commands) {
    test(`${provider}: ${command} source changes cannot admit work, effects or preview`, async t => {
      const {store} = await factory(t);
      const {invoke, operation_id, initial} = await coordinationCommandFixture(store, command);
      const source = await sourceFixture(t);
      for (const dryRun of [false, true]) for (const duringRead of [false, true]) {
        await source.restore();
        if (!duringRead) await source.revoke();
        const target = duringRead ? afterLoad(store, source.revoke) : store;
        const rejected = await invoke(target, {authoritySourcesCurrent: source.check, dryRun});
        assert.equal(rejected.reason_code, "authority_source_changed", JSON.stringify(rejected));
        assert.notEqual(rejected.changed, true);
        assert.deepEqual(await store.loadAuthority(), initial, "all Todos, leases and head metadata are preserved");
        assert.equal((await store.readReceipt(operation_id)).status, "missing");
      }
      if (command === "complete") {
        await source.restore();
        const rejected = await invoke(afterLoad(store, source.revoke), {
          authoritySourcesCurrent: source.check, pendingValidation: true,
        });
        assert.equal(rejected.reason_code, "authority_source_changed", "do not issue a validation effect on stale facts");
        assert.deepEqual(await store.loadAuthority(), initial);
      }
      await source.restore();
      assert.equal((await invoke(store, {authoritySourcesCurrent: source.check})).status, "applied");
    });

    test(`${provider}: ${command} source witness does not rewrite historical receipt identity`, async t => {
      const {store} = await factory(t);
      const {invoke, operation_id} = await coordinationCommandFixture(store, command);
      const source = await sourceFixture(t);
      // A receipt written under the previous fact contract is still the same
      // immutable operation when the witnessed transport retries it.
      assert.equal((await invoke(store)).status, "applied");
      const head = await store.loadAuthority(), receipt = await store.readReceipt(operation_id);
      assert.equal(receipt.status, "found");
      assert.equal((await invoke(store, {authoritySourcesCurrent: source.check})).status, "replayed");
      for (const invalidate of [source.revoke, source.remove]) {
        await invalidate();
        const result = await invoke(store, {authoritySourcesCurrent: source.check});
        if (command === "claim") {
          assert.equal(result.reason_code, "authority_source_changed");
          assert.ok(result.original_receipt, "current rejection preserves the historical claim");
        } else assert.equal(result.status, "replayed", JSON.stringify(result));
        assert.deepEqual(await store.loadAuthority(), head);
        assert.deepEqual(await store.readReceipt(operation_id), receipt);
      }
    });
  }
}
