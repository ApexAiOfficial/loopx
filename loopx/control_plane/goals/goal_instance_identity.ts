import type { JsonObject } from "../effect_program.ts";
import { assertNever, jsonObject } from "../runtime_decode.ts";

const GOAL_BINDING_MATCH_SCHEMA_VERSION = "loopx_goal_binding_match_v1";
const GOAL_ID = /^[A-Za-z0-9._:-]{1,200}$/;
const GOAL_INSTANCE_ID = /^ginst_[0-9a-f]{32}$/;

export type GoalId = Readonly<{
  kind: "goal_id";
  value: string;
}>;

export type GoalInstanceId = Readonly<{
  kind: "goal_instance_id";
  value: string;
}>;

export type ExactGoalRef = Readonly<{
  kind: "goal_ref";
  goalId: GoalId;
  goalInstanceId: GoalInstanceId;
}>;

type GoalRef =
  | Readonly<{
    kind: "legacy_goal_ref";
    goalId: GoalId;
  }>
  | ExactGoalRef;

export type ExactGoalRefParseResult =
  | Readonly<{ kind: "parsed"; value: ExactGoalRef }>
  | Readonly<{
    kind: "invalid";
    issue:
      | "invalid_goal_id"
      | "missing_goal_instance_id"
      | "invalid_goal_instance_id";
  }>;

type BindingOwner = "source_registry" | "global_projection";
type IdentitySide = "authority" | "binding";
type UnavailableReason = "registry_missing" | "registry_unreadable";

type IdentityIssue =
  | Readonly<{ kind: "invalid_observation" }>
  | Readonly<{ kind: "invalid_binding_owner" }>
  | Readonly<{ kind: "invalid_authority" }>
  | Readonly<{ kind: "invalid_goal_id"; side: IdentitySide }>
  | Readonly<{ kind: "invalid_goal_instance_id"; side: IdentitySide }>
  | Readonly<{ kind: "goal_id_mismatch" }>
  | Readonly<{
    kind: "authority_unavailable";
    reason: UnavailableReason;
  }>;

type GoalRefIssue = Extract<
  IdentityIssue,
  Readonly<{
    kind: "invalid_goal_id" | "invalid_goal_instance_id";
    side: IdentitySide;
  }>
>;

type Parsed<Value> =
  | Readonly<{ kind: "parsed"; value: Value }>
  | Readonly<{ kind: "invalid"; issue: IdentityIssue }>;

type ParsedGoalRef =
  | Readonly<{ kind: "parsed"; value: GoalRef }>
  | Readonly<{ kind: "invalid"; issue: GoalRefIssue }>;

type Authority =
  | Readonly<{ kind: "present"; goal: GoalRef }>
  | Readonly<{ kind: "absent" }>
  | Readonly<{ kind: "resolution_in_progress" }>
  | Readonly<{ kind: "unavailable"; reason: UnavailableReason }>;

function parseBindingOwner(value: unknown): Parsed<BindingOwner> {
  if (value === "source_registry" || value === "global_projection") {
    return { kind: "parsed", value };
  }
  return { kind: "invalid", issue: { kind: "invalid_binding_owner" } };
}

function parseGoalRef(value: unknown, side: IdentitySide): ParsedGoalRef {
  const raw = jsonObject(value);
  if (!raw || typeof raw.goal_id !== "string" || !GOAL_ID.test(raw.goal_id)) {
    return {
      kind: "invalid",
      issue: { kind: "invalid_goal_id", side },
    };
  }
  const goalId: GoalId = { kind: "goal_id", value: raw.goal_id };
  if (!Object.hasOwn(raw, "goal_instance_id")) {
    return {
      kind: "parsed",
      value: { kind: "legacy_goal_ref", goalId },
    };
  }
  if (
    typeof raw.goal_instance_id !== "string"
    || !GOAL_INSTANCE_ID.test(raw.goal_instance_id)
  ) {
    return {
      kind: "invalid",
      issue: { kind: "invalid_goal_instance_id", side },
    };
  }
  const goalInstanceId: GoalInstanceId = {
    kind: "goal_instance_id",
    value: raw.goal_instance_id,
  };
  return {
    kind: "parsed",
    value: { kind: "goal_ref", goalId, goalInstanceId },
  };
}

export function parseExactGoalRef(value: unknown): ExactGoalRefParseResult {
  const parsed = parseGoalRef(value, "binding");
  if (parsed.kind === "invalid") {
    return { kind: "invalid", issue: parsed.issue.kind };
  }
  if (parsed.value.kind === "legacy_goal_ref") {
    return { kind: "invalid", issue: "missing_goal_instance_id" };
  }
  return { kind: "parsed", value: parsed.value };
}

function parseAuthority(value: unknown): Parsed<Authority> {
  const raw = jsonObject(value);
  if (!raw) {
    return { kind: "invalid", issue: { kind: "invalid_authority" } };
  }
  if (raw.kind === "present") {
    const goal = parseGoalRef(raw.goal, "authority");
    return goal.kind === "parsed"
      ? { kind: "parsed", value: { kind: "present", goal: goal.value } }
      : goal;
  }
  if (raw.kind === "absent") {
    return { kind: "parsed", value: { kind: "absent" } };
  }
  if (raw.kind === "resolution_in_progress") {
    return {
      kind: "parsed",
      value: { kind: "resolution_in_progress" },
    };
  }
  if (
    raw.kind === "unavailable"
    && (raw.reason === "registry_missing"
      || raw.reason === "registry_unreadable")
  ) {
    return {
      kind: "parsed",
      value: { kind: "unavailable", reason: raw.reason },
    };
  }
  return { kind: "invalid", issue: { kind: "invalid_authority" } };
}

function wireRef(ref: GoalRef): JsonObject {
  switch (ref.kind) {
    case "legacy_goal_ref":
      return { goal_id: ref.goalId.value };
    case "goal_ref":
      return {
        goal_id: ref.goalId.value,
        goal_instance_id: ref.goalInstanceId.value,
      };
    default:
      return assertNever(ref, "unsupported Goal reference");
  }
}

function invalidResult(
  owner: BindingOwner | null,
  issue: IdentityIssue,
): JsonObject {
  return {
    schema_version: GOAL_BINDING_MATCH_SCHEMA_VERSION,
    mode: "observe_only",
    kind: "invalid",
    ...(owner ? { binding_owner: owner } : {}),
    issues: [issue],
  };
}

/**
 * Classify one source-and-binding observation without authorizing an action.
 */
export function projectGoalBindingMatch(value: unknown): JsonObject {
  const raw = jsonObject(value);
  if (!raw) {
    return invalidResult(null, { kind: "invalid_observation" });
  }
  const owner = parseBindingOwner(raw.binding_owner);
  if (owner.kind === "invalid") {
    return invalidResult(null, owner.issue);
  }
  const binding = parseGoalRef(raw.binding, "binding");
  if (binding.kind === "invalid") {
    return invalidResult(owner.value, binding.issue);
  }
  const authority = parseAuthority(raw.authority);
  if (authority.kind === "invalid") {
    return invalidResult(owner.value, authority.issue);
  }

  const base = {
    schema_version: GOAL_BINDING_MATCH_SCHEMA_VERSION,
    mode: "observe_only",
    binding_owner: owner.value,
  };
  switch (authority.value.kind) {
    case "unavailable":
      return invalidResult(owner.value, {
        kind: "authority_unavailable",
        reason: authority.value.reason,
      });
    case "absent":
      return {
        ...base,
        kind: "goal_not_registered",
        observed: wireRef(binding.value),
      };
    case "resolution_in_progress":
      return {
        ...base,
        kind: "resolution_in_progress",
        observed: wireRef(binding.value),
      };
    case "present":
      break;
    default:
      return assertNever(authority.value, "unsupported Goal authority");
  }

  const expected = authority.value.goal;
  const observed = binding.value;
  if (expected.goalId.value !== observed.goalId.value) {
    return invalidResult(owner.value, { kind: "goal_id_mismatch" });
  }
  if (expected.kind === "legacy_goal_ref") {
    if (observed.kind === "legacy_goal_ref") {
      return {
        ...base,
        kind: "legacy_read_only",
        goal_ref: wireRef(expected),
      };
    }
    return {
      ...base,
      kind: "goal_instance_mismatch",
      mismatch: {
        kind: "stamped_binding_against_legacy_goal",
        expected: wireRef(expected),
        observed: wireRef(observed),
      },
    };
  }
  if (observed.kind === "legacy_goal_ref") {
    return {
      ...base,
      kind: "missing_goal_instance_id",
      expected: wireRef(expected),
      observed: wireRef(observed),
    };
  }
  if (expected.goalInstanceId.value !== observed.goalInstanceId.value) {
    return {
      ...base,
      kind: "goal_instance_mismatch",
      mismatch: {
        kind: "different_instance",
        expected: wireRef(expected),
        observed: wireRef(observed),
      },
    };
  }
  return {
    ...base,
    kind: "current",
    goal_ref: wireRef(expected),
  };
}
