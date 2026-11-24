import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { isProjectionDelivery, parseProjectionDelivery, projectionDelivery } from "../../loopx/control_plane/todos/projection_delivery.ts";

test("projection delivery maps mutation and no-op outcomes", () => {
  assert.equal(projectionDelivery(true), "pending");
  assert.equal(projectionDelivery(false), "not_required");
});

test("projection delivery parser accepts provider readback states", () => {
  for (const value of ["pending", "delivered", "current", "not_required"]) {
    assert.equal(parseProjectionDelivery(value), value);
  }
  assert.throws(() => parseProjectionDelivery("unknown"));
  assert.equal(isProjectionDelivery("delivered"), true);
  assert.equal(isProjectionDelivery("DELIVERED"), false);
  assert.equal(isProjectionDelivery(null), false);
});

test("composition fixture keeps mutation and provider states distinct", async () => {
  const fixture = JSON.parse(await readFile("tests/fixtures/control_plane/projection_delivery_composition_v0.json", "utf8"));
  for (const item of fixture.cases) {
    const actual = item.changed === undefined ? parseProjectionDelivery(item.readback) : projectionDelivery(item.changed);
    assert.equal(actual, item.expected, item.name);
    assert.equal(item.requires_ack, actual === "delivered" || actual === "current", item.name);
  }
});

test("end-to-end fixture preserves delivery causal chain", async () => {
  const fixture = JSON.parse(await readFile("tests/fixtures/control_plane/projection_delivery_e2e_v1.json", "utf8"));
  const observed = fixture.transitions.map((item: { changed?: boolean; readback?: unknown }) =>
    item.readback === undefined ? projectionDelivery(item.changed === true) : parseProjectionDelivery(item.readback));
  assert.deepEqual(observed, ["pending", "delivered", "current", "not_required", "pending"]);
});

test("projection confirmation binds durable host readback to one observed revision", async () => {
  const {decodeProjectionReadback, confirmProjectionReadback} = await import("../../loopx/control_plane/todos/projection_delivery.ts");
  for (const changed of [true, false]) {
    const readback = decodeProjectionReadback({provider_revision: "revision-a", changed, attempt: 1, target: "latest"});
    assert.equal(confirmProjectionReadback(readback, "revision-a").status, changed ? "delivered" : "current");
    const overlap = confirmProjectionReadback(readback, "revision-b");
    assert.equal(overlap.status, "pending");
    assert.equal(overlap.next_action, "retry");
    assert.equal(overlap.observed_provider_revision, "revision-b");
  }
  for (const bad of [null, [], {}, {provider_revision: "", changed: false},
    {provider_revision: "a", changed: "true"}, {provider_revision: "a", changed: false, verified: true}]) {
    assert.throws(() => decodeProjectionReadback(bad));
  }
});


test("delivery retry is bounded and pinned requests cannot chase a new head", async () => {
  const {decodeProjectionReadback, confirmProjectionReadback} = await import("../../loopx/control_plane/todos/projection_delivery.ts");
  for (const target of ["pinned", "latest"]) for (const attempt of [1, 2, 3]) {
    const witness = decodeProjectionReadback({provider_revision: "old", changed: true, attempt, target});
    const pending = confirmProjectionReadback(witness, "new");
    assert.equal(pending.status, "pending");
    assert.equal(pending.next_action, target === "latest" && attempt < 3 ? "retry" : "finish");
    const current = confirmProjectionReadback(witness, "old");
    assert.equal(current.status, "delivered");
    assert.equal(current.next_action, "finish");
  }
  const valid = {provider_revision: "old", changed: true, attempt: 1, target: "latest"};
  for (const attempt of [0, -1, 1.5, 4, "1", null, Number.NaN]) {
    assert.throws(() => decodeProjectionReadback({...valid, attempt}));
  }
  for (const target of [null, "", "maybe", false]) {
    assert.throws(() => decodeProjectionReadback({...valid, target}));
  }
  assert.throws(() => decodeProjectionReadback({...valid, extra: true}));
});
