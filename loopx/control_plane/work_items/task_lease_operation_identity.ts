import {createHash} from "node:crypto";
import {TASK_LEASE_LIFECYCLE_REQUEST_SCHEMA} from "../coordination/coordination_state_contract.generated.ts";

export interface TaskLeaseOperationIdentityInput {
  operation: string;
  goal_id: string;
  todo_id: string;
  owner: string | null;
  idempotency_key: string | null;
  expected_version: number | null;
  ttl_seconds: number | null;
  new_owner: string | null;
  new_idempotency_key: string | null;
  transfer_claim?: boolean;
}

/** Preserve the legacy v0 digest encoding; changing it changes replay identity. */
export function taskLeaseStableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(taskLeaseStableValue);
  if (typeof value !== "object" || value === null) return value;
  return Object.fromEntries(Object.entries(value as Record<string, unknown>)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, child]) => [key, taskLeaseStableValue(child)]));
}

export function taskLeaseDigest(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(taskLeaseStableValue(value)), "utf8").digest("hex");
}

export function taskLeaseOperationIdentity(request: TaskLeaseOperationIdentityInput): string | null {
  if (!request.idempotency_key) return null;
  return taskLeaseDigest({schema_version: TASK_LEASE_LIFECYCLE_REQUEST_SCHEMA,
    operation: request.operation, goal_id: request.goal_id, todo_id: request.todo_id,
    owner: request.owner, idempotency_key: request.idempotency_key,
    expected_version: request.expected_version});
}

export function taskLeaseOperationRequestDigest(request: TaskLeaseOperationIdentityInput): string | null {
  if (!request.idempotency_key) return null;
  return taskLeaseDigest({schema_version: TASK_LEASE_LIFECYCLE_REQUEST_SCHEMA,
    operation: request.operation, goal_id: request.goal_id, todo_id: request.todo_id,
    owner: request.owner, idempotency_key: request.idempotency_key,
    expected_version: request.expected_version, ttl_seconds: request.ttl_seconds,
    new_owner: request.new_owner, new_idempotency_key: request.new_idempotency_key,
    // Preserve all v0 identities; an explicit coupled transfer cannot replay
    // a lease-only operation (or be downgraded to one on retry).
    ...(request.transfer_claim ? {transfer_claim: true} : {})});
}
