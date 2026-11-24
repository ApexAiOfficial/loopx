/** Canonical projection-delivery state returned by Todo mutations. */
export type TodoProjectionDelivery = "pending" | "delivered" | "current" | "not_required";
const PROJECTION_DELIVERY_VALUES = new Set<TodoProjectionDelivery>([
  "pending", "delivered", "current", "not_required",
]);

/** Keep mutation results consistent and make the no-op meaning explicit. */
export function projectionDelivery(changed: boolean): TodoProjectionDelivery {
  return changed ? "pending" : "not_required";
}

/** Decode provider readback without letting ad-hoc strings cross the boundary. */
export function parseProjectionDelivery(value: unknown): TodoProjectionDelivery {
  if (typeof value === "string" && PROJECTION_DELIVERY_VALUES.has(value as TodoProjectionDelivery)) {
    return value as TodoProjectionDelivery;
  }
  throw new Error(`projection_delivery is unsupported: ${String(value)}`);
}

export function isProjectionDelivery(value: unknown): value is TodoProjectionDelivery {
  return typeof value === "string" && PROJECTION_DELIVERY_VALUES.has(value as TodoProjectionDelivery);
}

/** Host attests durable file readback; the provider owns revision comparison.
 * Confirmation describes one observed head, never a lock on future commits. */
export interface ProjectionReadback {
  provider_revision: string;
  changed: boolean;
  attempt: number;
  target: "pinned" | "latest";
}

export function decodeProjectionReadback(value: unknown): ProjectionReadback {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("projection_readback must be an object");
  }
  const row = value as Record<string, unknown>;
  if (Object.keys(row).length !== 4 || typeof row.provider_revision !== "string" ||
      !row.provider_revision.trim() || row.provider_revision !== row.provider_revision.trim() ||
      typeof row.changed !== "boolean" ||
      typeof row.attempt !== "number" || !Number.isSafeInteger(row.attempt) || row.attempt < 1 ||
      row.attempt > 3 || (row.target !== "pinned" && row.target !== "latest")) throw new TypeError("invalid projection_readback");
  return {provider_revision: row.provider_revision, changed: row.changed,
    attempt: row.attempt, target: row.target};
}

/** One policy for mutation delivery, refresh recovery and explicit projection.
 * The display lock does not lock provider commits. Only a latest-head request
 * may follow an overlap; exact-revision requests must remain pinned.
 */
export type ProjectionConfirmation = {
  provider_revision: string;
  observed_provider_revision: string;
} & (
  | {status: "delivered" | "current"; next_action: "finish"}
  | {status: "pending"; next_action: "retry" | "finish";
     reason_code: "todo_projection_revision_advanced"; retryable: true;
     retry_business_mutation: false; recommended_action: string}
);

export function confirmProjectionReadback(
  readback: ProjectionReadback, observedRevision: string,
): ProjectionConfirmation {
  const basis = {provider_revision: readback.provider_revision,
    observed_provider_revision: observedRevision};
  if (readback.provider_revision === observedRevision) {
    return {...basis, status: readback.changed ? "delivered" : "current", next_action: "finish"};
  }
  return {...basis, status: "pending",
    next_action: readback.target === "latest" && readback.attempt < 3 ? "retry" : "finish",
    reason_code: "todo_projection_revision_advanced", retryable: true,
    retry_business_mutation: false,
    recommended_action: "Read the current provider revision with todo list, then retry todo project-markdown for that revision.",
  };
}
