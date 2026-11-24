import type { AuthorityStore } from "./authority_store.ts";
import {
  POSTGRESQL_STORE_IDENTITY_PATTERN,
  PostgreSqlAuthorityStore,
  type PostgreSqlAuthorityDatabase,
  type PostgreSqlAuthorityStoreOptions,
} from "./postgresql_authority_store.ts";
import { requireAuthorityStoreId } from "./authority_store_codec.ts";

/** A principal already verified by the service's authentication layer. */
export interface PostgreSqlAuthenticatedPrincipal {
  principal_id: string;
}

export type PostgreSqlPrincipalAuthenticationResult =
  | { status: "authenticated"; principal: PostgreSqlAuthenticatedPrincipal }
  | { status: "rejected"; reason_code: string; reason: string };

export type PostgreSqlTenantAuthorizationResult =
  | { status: "allowed" }
  | { status: "denied"; reason_code: string; reason: string };

/**
 * The service owns authentication and authorization. The provider only sees
 * an already verified principal id and the authorized tenant binding.
 */
export interface PostgreSqlAuthorityServiceDependencies {
  database: PostgreSqlAuthorityDatabase;
  authenticatePrincipal(
    credential: unknown,
  ): Promise<PostgreSqlPrincipalAuthenticationResult> | PostgreSqlPrincipalAuthenticationResult;
  authorizeTenant(
    principalId: string,
    tenantId: string,
  ): Promise<PostgreSqlTenantAuthorizationResult> | PostgreSqlTenantAuthorizationResult;
  max_commit_bytes?: PostgreSqlAuthorityStoreOptions["max_commit_bytes"];
}

export interface PostgreSqlAuthorityServiceOpenRequest {
  /** Opaque transport credential; never persisted or passed to PostgreSQL. */
  credential: unknown;
  tenant_id: string;
  goal_id: string;
  store_identity: string;
}

export type PostgreSqlAuthorityServiceOpenResult =
  | {
    status: "opened";
    provider: "postgresql";
    principal_id: string;
    tenant_id: string;
    goal_id: string;
    store_identity: string;
    store: AuthorityStore;
  }
  | {
    status: "rejected";
    reason_code:
      | "invalid_service_request"
      | "principal_unauthenticated"
      | "principal_verification_unavailable"
      | "tenant_unauthorized"
      | "tenant_authorization_unavailable"
      | "store_identity_unavailable"
      | "store_identity_mismatch";
    reason: string;
    principal_id?: string;
    tenant_id?: string;
    goal_id?: string;
  };

type PostgreSqlAuthorityServiceRejected = Extract<
  PostgreSqlAuthorityServiceOpenResult,
  {status: "rejected"}
>;

function rejected(
  reasonCode: PostgreSqlAuthorityServiceRejected["reason_code"],
  reason: string,
  facts: Partial<PostgreSqlAuthorityServiceRejected> = {},
): PostgreSqlAuthorityServiceRejected {
  return {status: "rejected", reason_code: reasonCode, reason, ...facts};
}

function validIdentity(value: string): boolean {
  return POSTGRESQL_STORE_IDENTITY_PATTERN.test(value);
}

/**
 * Service-owned PostgreSQL admission. This is intentionally an in-process
 * boundary: transport authentication, pool lifecycle, and credentials stay
 * outside the provider-neutral AuthorityStore contract.
 */
export class PostgreSqlAuthorityService {
  readonly #dependencies: PostgreSqlAuthorityServiceDependencies;

  constructor(dependencies: PostgreSqlAuthorityServiceDependencies) {
    this.#dependencies = dependencies;
  }

  async openStore(
    request: PostgreSqlAuthorityServiceOpenRequest,
  ): Promise<PostgreSqlAuthorityServiceOpenResult> {
    let tenantId: string;
    let goalId: string;
    if (
      typeof request !== "object" || request === null ||
      typeof request.tenant_id !== "string" ||
      typeof request.goal_id !== "string" ||
      typeof request.store_identity !== "string"
    ) {
      return rejected("invalid_service_request", "PostgreSQL service request is invalid");
    }
    try {
      tenantId = requireAuthorityStoreId(request.tenant_id, "tenant id");
      goalId = requireAuthorityStoreId(request.goal_id, "goal id");
    } catch (error) {
      return rejected(
        "invalid_service_request",
        error instanceof Error ? error.message : "PostgreSQL service request is invalid",
      );
    }
    if (!validIdentity(request.store_identity)) {
      return rejected(
        "invalid_service_request",
        "PostgreSQL store identity must match postgresql:<32 lowercase hex>",
        {tenant_id: tenantId, goal_id: goalId},
      );
    }

    let authentication: PostgreSqlPrincipalAuthenticationResult;
    try {
      authentication = await this.#dependencies.authenticatePrincipal(request.credential);
    } catch {
      return rejected(
        "principal_verification_unavailable",
        "PostgreSQL service could not verify the principal",
        {tenant_id: tenantId, goal_id: goalId},
      );
    }
    if (authentication.status !== "authenticated") {
      return rejected(
        "principal_unauthenticated",
        "PostgreSQL service principal authentication was rejected",
        {tenant_id: tenantId, goal_id: goalId},
      );
    }

    let principalId: string;
    try {
      principalId = requireAuthorityStoreId(
        authentication.principal.principal_id,
        "principal id",
      );
    } catch {
      return rejected(
        "principal_unauthenticated",
        "PostgreSQL service returned an invalid authenticated principal",
        {tenant_id: tenantId, goal_id: goalId},
      );
    }

    let tenantDecision: PostgreSqlTenantAuthorizationResult;
    try {
      tenantDecision = await this.#dependencies.authorizeTenant(principalId, tenantId);
    } catch {
      return rejected(
        "tenant_authorization_unavailable",
        "PostgreSQL service could not authorize the tenant",
        {principal_id: principalId, tenant_id: tenantId, goal_id: goalId},
      );
    }
    if (tenantDecision.status !== "allowed") {
      return rejected(
        "tenant_unauthorized",
        "PostgreSQL principal is not authorized for the requested tenant",
        {principal_id: principalId, tenant_id: tenantId, goal_id: goalId},
      );
    }

    const store = new PostgreSqlAuthorityStore(this.#dependencies.database, {
      tenant_id: tenantId,
      goal_id: goalId,
      max_commit_bytes: this.#dependencies.max_commit_bytes,
    });
    const identity = await store.storeIdentity();
    if (identity.status !== "available") {
      return rejected(
        "store_identity_unavailable",
        "PostgreSQL service could not verify the database incarnation",
        {principal_id: principalId, tenant_id: tenantId, goal_id: goalId},
      );
    }
    if (identity.store_identity !== request.store_identity) {
      return rejected(
        "store_identity_mismatch",
        "PostgreSQL database incarnation does not match the requested binding",
        {principal_id: principalId, tenant_id: tenantId, goal_id: goalId},
      );
    }
    return {
      status: "opened",
      provider: "postgresql",
      principal_id: principalId,
      tenant_id: tenantId,
      goal_id: goalId,
      store_identity: identity.store_identity,
      store,
    };
  }
}
