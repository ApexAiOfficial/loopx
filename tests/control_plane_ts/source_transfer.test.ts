import assert from "node:assert/strict";
import test from "node:test";
import {createHash} from "node:crypto";
import {mkdtemp, realpath, rm, writeFile, readFile, symlink, chmod} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {withCoordinationSourceTransfer, SOURCE_TRANSFER_SCHEMA, SOURCE_TRANSFER_RESULT_SCHEMA,
  MAX_SOURCE_TRANSFER_BYTES} from "../../loopx/control_plane/coordination/source_transfer.ts";
import {projectCoordinationSource, SOURCE_PROJECTION_REQUEST_SCHEMA} from "../../loopx/control_plane/coordination/source_projection.ts";

const method = "coordination.source.project";
const hash = (bytes: Uint8Array) => createHash("sha256").update(bytes).digest("hex");
async function transfer(t: test.TestContext, value: unknown) {
  const directory = await realpath(await mkdtemp(join(tmpdir(), "loopx-source-test-")));
  t.after(() => rm(directory, {recursive: true, force: true}));
  const bytes = Buffer.from(JSON.stringify(value));
  await writeFile(join(directory, "request.json"), bytes);
  return {schema_version: SOURCE_TRANSFER_SCHEMA, method, directory,
    request_sha256: hash(bytes), request_bytes: bytes.length};
}
const source = {schema_version: SOURCE_PROJECTION_REQUEST_SCHEMA, kind: "snapshot", goal_id: "goal",
  handoff_mode: "soft_claim", read_model_schema: "loopx_todo_canonical_read_record_v0", leases: [],
  todos: [{schema_version: "todo_item_v0", todo_id: "a", role: "agent", text: "Retained work", status: "open", done: false,
    archive_state: "active", source_section: "Agent Todo"}]};

test("complete source and result exceed RPC size without losing records or bypassing the typed owner", async t => {
  const todos = Array.from({length: 160}, (_, i) => ({...source.todos[0], todo_id: `t${i.toString().padStart(3, "0")}`,
    note: "完整🙂".repeat(1600)}));
  const request = {...source, todos};
  const envelope = await transfer(t, request);
  assert.ok(envelope.request_bytes > 2 * 1024 * 1024);
  const result = await withCoordinationSourceTransfer(method, projectCoordinationSource)(envelope) as Record<string, unknown>;
  assert.equal(result.schema_version, SOURCE_TRANSFER_RESULT_SCHEMA);
  assert.equal(result.request_sha256, envelope.request_sha256);
  assert.ok(Buffer.byteLength(JSON.stringify(result)) < 512);
  const bytes = await readFile(join(envelope.directory, "result.json"));
  assert.equal(bytes.length, result.result_bytes);
  assert.equal(hash(bytes), result.result_sha256);
  const projection = JSON.parse(bytes.toString()).projection;
  assert.deepEqual(projection.todos, todos);
  assert.equal(projection.todo_read_model.todo_count, 160);
  assert.deepEqual(projection.leases, []);
});

test("inline protocol remains usable and semantic errors are not converted to empty success", async t => {
  const handler = withCoordinationSourceTransfer(method, projectCoordinationSource);
  assert.deepEqual(await handler(source), projectCoordinationSource(source));
  await assert.rejects(handler(await transfer(t, {...source, todos: [source.todos[0], source.todos[0]]})), /duplicate todos/);
});

for (const change of ["digest", "method", "size", "extra", "oversize", "replaced", "output"] as const) {
  test(`reject ${change} before running business code`, async t => {
    const envelope: Record<string, unknown> = await transfer(t, source);
    const directory = String(envelope.directory);
    if (change === "digest") envelope.request_sha256 = "0".repeat(64);
    if (change === "method") envelope.method = "coordination.runtime_shadow.bootstrap";
    if (change === "size") envelope.request_bytes = Number(envelope.request_bytes) - 1;
    if (change === "oversize") envelope.request_bytes = MAX_SOURCE_TRANSFER_BYTES + 1;
    if (change === "extra") envelope.output_path = join(directory, "unexpected.json");
    if (change === "replaced") await writeFile(join(directory, "request.json"), JSON.stringify(source).replace("Retained", "Tampered"));
    if (change === "output") await writeFile(join(directory, "result.json"), "do not overwrite");
    let called = false;
    await assert.rejects(withCoordinationSourceTransfer(method, () => {called = true; return {}; })(envelope));
    assert.equal(called, false);
    if (change === "output") assert.equal(await readFile(join(directory, "result.json"), "utf8"), "do not overwrite");
  });
}

test("request symlink and shared directory reject", {skip: process.platform === "win32"}, async t => {
  const envelope = await transfer(t, source);
  const path = join(envelope.directory, "request.json");
  const original = await readFile(path);
  await writeFile(join(envelope.directory, "other.json"), original);
  await rm(path);
  await symlink(join(envelope.directory, "other.json"), path);
  const handler = withCoordinationSourceTransfer(method, () => assert.fail("must not execute"));
  await assert.rejects(handler(envelope), /regular file/);
  await chmod(envelope.directory, 0o755);
  await assert.rejects(handler(envelope), /private/);
});

test("artifact budget also bounds returned bytes", async t => {
  const envelope = await transfer(t, {});
  await assert.rejects(withCoordinationSourceTransfer(method,
    () => ({value: "x".repeat(MAX_SOURCE_TRANSFER_BYTES)}))(envelope), /exceeds 16 MiB/);
  assert.equal((await readFile(join(envelope.directory, "result.json"))).length, 0);
});
