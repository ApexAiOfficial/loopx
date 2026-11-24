import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import type {
  AuthorityStore,
  AuthorityStoreCommit,
  AuthorityStoreReceiptResult,
  AuthorityStoreScanResult,
} from "../../loopx/control_plane/coordination/authority_store.ts";
import { FileAuthorityStore } from "../../loopx/control_plane/coordination/file_authority_store.ts";
import { canonicalAuthoritySha256 } from "../../loopx/control_plane/coordination/authority_store_codec.ts";
import {
  commitPromotionAndReadBack,
  readPromotionReceipt,
} from "../../loopx/control_plane/coordination/promotion_receipt.ts";

async function fixture(t: test.TestContext) {
  const root = await mkdtemp(join(tmpdir(), "promotion-receipt-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const store = new FileAuthorityStore(root, "goal-a");
  const projection = { goal_id: "goal-a", todos: [], leases: [], handoff_mode: "hard_lease" };
  const receipt = { schema_version: "promotion-test-receipt", operation_id: "promotion", plan: "reviewed" };
  const identity = {
    operation_id: "promotion",
    receipt,
    projection_sha256: canonicalAuthoritySha256(projection),
  };
  const committed = await commitPromotionAndReadBack(store, identity, projection, { kind: "promotion" });
  assert.equal(committed.readback.matched, true);
  return { store, projection, identity };
}

// The receipt index and first transaction are independent proof surfaces. A
// provider bug in either cannot certify cutover just because the other matches.
for (const mutation of [
  "receipt_revision",
  "receipt_cursor",
  "receipt_content",
  "first_revision",
  "first_cursor",
  "first_receipt",
  "first_projection",
  "first_operation",
  "empty_lineage",
] as const) {
  test(`promotion proof rejects ${mutation} divergence`, async (t) => {
    const { store, identity } = await fixture(t);
    const proxy = new Proxy(store, {
      get(target, key) {
        if (key === "readReceipt")
          return async (operation: string): Promise<AuthorityStoreReceiptResult> => {
            const found = await target.readReceipt(operation);
            if (found.status !== "found") return found;
            if (mutation === "receipt_revision") return { ...found, provider_revision: "another-revision" };
            if (mutation === "receipt_cursor") return { ...found, cursor: "2" };
            if (mutation === "receipt_content") return { ...found, receipts: [{ wrong: true }] };
            return found;
          };
        if (key === "scanCommitted")
          return async (): Promise<AuthorityStoreScanResult> => {
            const page = await target.scanCommitted(null, 1);
            if (page.status !== "page") return page;
            const first = structuredClone(page.transactions[0]);
            if (mutation === "first_revision") first.provider_revision = "another-revision";
            if (mutation === "first_cursor") first.cursor = "2";
            if (mutation === "first_receipt") first.receipts = [{ wrong: true }];
            if (mutation === "first_projection") first.projection = { wrong: true };
            if (mutation === "first_operation") first.operation_id = "another-operation";
            return { ...page, transactions: mutation === "empty_lineage" ? [] : [first] };
          };
        const member = Reflect.get(target, key);
        return typeof member === "function" ? member.bind(target) : member;
      },
    });
    const before = await store.loadAuthority();
    assert.equal((await readPromotionReceipt(proxy, identity)).matched, false);
    assert.deepEqual(await store.loadAuthority(), before);
  });
}

test("an unavailable proof read is not silently converted into commit absence", async (t) => {
  const { store, identity } = await fixture(t);
  const proxy = new Proxy(store, {
    get(target, key) {
      if (key === "readReceipt")
        return async () => {
          throw new Error("receipt transport unavailable");
        };
      const value = Reflect.get(target, key);
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
  await assert.rejects(readPromotionReceipt(proxy, identity), /receipt transport unavailable/);
});

test("failed commit evidence cannot be upgraded by an unrelated successful receipt", async (t) => {
  const { store, identity, projection } = await fixture(t);
  let attempts = 0;
  const proxy: AuthorityStore = new Proxy(store, {
    get(target, key) {
      if (key === "commitAuthority")
        return async (_request: AuthorityStoreCommit) => {
          attempts++;
          throw new Error("uncertain transport outcome");
        };
      const value = Reflect.get(target, key);
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
  const result = await commitPromotionAndReadBack(
    proxy,
    { ...identity, operation_id: "other-operation" },
    projection,
    {},
  );
  assert.equal(result.interrupted, true);
  assert.equal(result.commit, null);
  assert.deepEqual(result.readback, {
    matched: false,
    reason_code: "local_authority_promotion_receipt_missing",
  });
  assert.equal(attempts, 1, "the helper never blindly retries a business commit");
});

for (const method of ["readReceipt", "scanCommitted"] as const) {
  test(`typed ${method} unavailability retains its actionable provider reason`, async t => {
    const {store, identity} = await fixture(t);
    const proxy = new Proxy(store, {get(target, key) {
      if (key === method) return async () => ({status: "unavailable", reason_code: "provider_offline", reason: "offline"});
      const member = Reflect.get(target, key);
      return typeof member === "function" ? member.bind(target) : member;
    }});
    assert.deepEqual(await readPromotionReceipt(proxy, identity), {matched: false, reason_code: "provider_offline"});
  });
}
