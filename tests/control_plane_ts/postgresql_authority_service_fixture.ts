import {readFileSync} from "node:fs";

const envelope = JSON.parse(readFileSync(new URL(
  "../fixtures/control_plane/postgresql_authority_service_v0.json",
  import.meta.url,
), "utf8")) as PostgreSqlAuthorityServiceFixture;

export const POSTGRESQL_AUTHORITY_SERVICE_FIXTURE_SCHEMA =
  "loopx_postgresql_authority_service_fixture_v0";

export interface PostgreSqlAuthorityServiceFixtureCase {
  readonly id: string;
  readonly credential_kind?: "opaque";
  readonly expected: "opened" | "rejected" | "rotated" | "failed";
  readonly reason_code?: string;
}

export interface PostgreSqlAuthorityServiceFixture {
  readonly schema_version: string;
  readonly source_authority: "postgresql_v0";
  readonly principal_cases: readonly PostgreSqlAuthorityServiceFixtureCase[];
  readonly rotation_cases: readonly PostgreSqlAuthorityServiceFixtureCase[];
  readonly credential_persistence: "forbidden";
  readonly agent_database_access: "forbidden";
}

if (envelope.schema_version !== POSTGRESQL_AUTHORITY_SERVICE_FIXTURE_SCHEMA) {
  throw new Error("PostgreSQL authority service fixture schema version is invalid");
}

export const postgresqlAuthorityServiceFixture: PostgreSqlAuthorityServiceFixture =
  structuredClone(envelope);
