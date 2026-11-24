/** Complete coordination capture assembly. File IO remains in the source adapter;
 * identity, membership, ordering and the consumer manifest share the TS owner. */
import type {HandoffMode} from "./handoff_mode_policy.ts";
import {EffectRuntimeRequestError} from "../effect_runtime_errors.ts";
import type {JsonObject} from "../effect_program.ts";
import {AuthorityStoreProtocolError, authorityUnicodeCompare, canonicalAuthorityObject,
  hasExactAuthorityKeys, requireAuthorityStoreId} from "./authority_store_codec.ts";
import {canonicalCoordinationTodoRecord, TODO_CANONICAL_READ_RECORD_SCHEMA, TODO_DOMAIN_READ_RECORD_SCHEMA,
  TODO_DOMAIN_ITEM_SCHEMA, TODO_ITEM_SCHEMA} from "./coordination_state_contract.ts";
import {LOCAL_AUTHORITY_SHADOW_TRANSACTION_PROJECTION_SCHEMA} from "./coordination_state_contract.generated.ts";
import {canonicalTodoRecord} from "./todo_presentation.ts";
import {coordinationTodoReadModel} from "./coordination_projection.ts";

export const SOURCE_PROJECTION_REQUEST_SCHEMA = "coordination_source_projection_request_v0";
export const SOURCE_PROJECTION_RESULT_SCHEMA = "coordination_source_projection_result_v0";

type SourceProjectionRequest =
  | {kind: "todo_partition"; handoff_mode: HandoffMode; todos: readonly JsonObject[]}
  | {kind: "snapshot"; handoff_mode: HandoffMode; todos: readonly JsonObject[];
      goal_id: string; leases: readonly JsonObject[]; read_model_schema: typeof TODO_CANONICAL_READ_RECORD_SCHEMA | typeof TODO_DOMAIN_READ_RECORD_SCHEMA};

function fail(message: string): never {
  throw new AuthorityStoreProtocolError(`coordination source projection: ${message}`);
}

/** Python integers must not become rounded JS Numbers before a source digest.
 * Floating point observations do not belong to this persisted capture contract. */
function requireExactNumbers(value: unknown, path: string): void {
  if (typeof value === "number" && !Number.isSafeInteger(value)) fail(`${path} requires a safe integer`);
  if (Array.isArray(value)) value.forEach((item, index) => requireExactNumbers(item, `${path}[${index}]`));
  else if (value !== null && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) requireExactNumbers(item, `${path}.${key}`);
  }
}

function records(value: unknown, label: string): JsonObject[] {
  if (!Array.isArray(value)) fail(`${label} must be an array; missing source is not empty evidence`);
  const ids = new Set<string>();
  return value.map((raw, index) => {
    const item = canonicalAuthorityObject(raw, `${label}[${index}]`);
    const id = requireAuthorityStoreId(item.todo_id, `${label}[${index}].todo_id`);
    if (ids.has(id)) fail(`duplicate ${label} identity: ${id}`);
    ids.add(id);
    return item;
  });
}

function decode(value: unknown): SourceProjectionRequest {
  const input = canonicalAuthorityObject(value, "coordination source projection request");
  requireExactNumbers(input, "request");
  const common = ["schema_version", "kind", "handoff_mode", "todos"];
  const kind = input.kind;
  if (input.schema_version !== SOURCE_PROJECTION_REQUEST_SCHEMA ||
      (kind !== "todo_partition" && kind !== "snapshot") ||
      !hasExactAuthorityKeys(input, kind === "snapshot" ? [...common, "goal_id", "leases", "read_model_schema"] : common)) {
    fail("request schema or fields mismatch");
  }
  if (input.handoff_mode !== "legacy" && input.handoff_mode !== "soft_claim" && input.handoff_mode !== "hard_lease") {
    fail("unsupported handoff mode");
  }
  // Bind the narrowed mode once: an object literal property would widen the
  // checked literal union back to string and lose the request contract.
  const handoffMode: HandoffMode = input.handoff_mode;
  const readSchema = kind === "todo_partition" ? TODO_CANONICAL_READ_RECORD_SCHEMA : input.read_model_schema;
  if (readSchema !== TODO_CANONICAL_READ_RECORD_SCHEMA && readSchema !== TODO_DOMAIN_READ_RECORD_SCHEMA) {
    fail("unsupported Todo read-model schema");
  }
  const todos = records(input.todos, "todos").map((item, index) => {
    // Evaluation is a transient query result, never a source field. This is
    // the sole accepted adapter-only field; arbitrary unknown fields reject.
    const {succession_evaluation: _evaluation, ...record} = item;
    if (record.schema_version !== undefined && record.schema_version !== TODO_ITEM_SCHEMA && record.schema_version !== TODO_DOMAIN_ITEM_SCHEMA) {
      fail("unsupported Todo record schema");
    }
    const validated = kind === "todo_partition" || record.schema_version === undefined
      ? canonicalCoordinationTodoRecord(record, `canonical Todo read record ${index}`)
      : canonicalTodoRecord(record, `canonical Todo read record ${index}`);
    return validated;
  }).sort((left, right) => authorityUnicodeCompare(String(left.todo_id), String(right.todo_id)));
  const shared = {handoff_mode: handoffMode, todos};
  if (kind === "todo_partition") return {kind, ...shared};
  const goalId = requireAuthorityStoreId(input.goal_id, "goal id");
  const leases = records(input.leases, "leases");
  // Check *all* identities before excluding retained history. An orphan record
  // from another Goal is corruption, not a disposable historical lease.
  for (const lease of leases) {
    if (lease.goal_id !== undefined && lease.goal_id !== goalId) fail(`lease ${lease.todo_id} belongs to another Goal`);
  }
  return {kind, ...shared, goal_id: goalId, leases, read_model_schema: readSchema};
}

/** Source capture, source revalidation and Todo-partition folding share membership. */
export function currentGraphTodoIds(todos: readonly JsonObject[]): Set<string> {
  return new Set(todos.filter(todo => todo.archive_state === "active").map(todo => String(todo.todo_id)));
}

export function projectCoordinationSource(value: unknown): JsonObject {
  let request: SourceProjectionRequest;
  try { request = decode(value); }
  catch (error) {
    if (error instanceof AuthorityStoreProtocolError) throw new EffectRuntimeRequestError(error.message);
    throw error;
  }
  const partition = {handoff_mode: request.handoff_mode, todos: [...request.todos]};
  if (request.kind === "todo_partition") {
    return {schema_version: SOURCE_PROJECTION_RESULT_SCHEMA, projection: partition};
  }
  // The lease directory is retained history; only active-section membership
  // enters the current graph. Do not test liveness here: released/expired
  // records for retained Todos preserve the generation watermark.
  const currentIds = currentGraphTodoIds(request.todos);
  const leases = request.leases.filter(lease => currentIds.has(String(lease.todo_id)))
    .sort((left, right) => authorityUnicodeCompare(String(left.todo_id), String(right.todo_id)));
  return {schema_version: SOURCE_PROJECTION_RESULT_SCHEMA, projection: {
    schema_version: LOCAL_AUTHORITY_SHADOW_TRANSACTION_PROJECTION_SCHEMA,
    goal_id: request.goal_id, source_authority: "legacy_markdown_and_task_lease",
    ...partition, leases,
    todo_read_model: coordinationTodoReadModel(request.todos, request.read_model_schema),
    partitions: {todos: null, leases: null},
  }};
}
