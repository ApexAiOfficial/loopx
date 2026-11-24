import type {JsonObject} from "../effect_program.ts";
import {AuthorityStoreProtocolError} from "./authority_store_codec.ts";
import {normalizeWriteScopes} from "../work_items/task_lease_acquire.ts";

/** Canonical Todo write scopes shared by claim/lease admission and migration. */
export function coordinationTodoWriteScopes(todo: JsonObject): string[] {
  const requiredWriteScopes = todo.required_write_scopes ?? [];
  if (!Array.isArray(requiredWriteScopes) ||
      requiredWriteScopes.some((scope) => typeof scope !== "string")) {
    throw new AuthorityStoreProtocolError(
      "todo.required_write_scopes must be an array of strings",
    );
  }
  const writeScopes = normalizeWriteScopes(requiredWriteScopes);
  if (writeScopes.length !== requiredWriteScopes.length) {
    throw new AuthorityStoreProtocolError(
      "todo.required_write_scopes contains an invalid or duplicate scope",
    );
  }
  return writeScopes;
}
