import assert from "node:assert/strict";
import test from "node:test";

import { projectGoalBindingMatch } from "../../loopx/control_plane/goals/goal_instance_identity.ts";

const INSTANCE_A = "ginst_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const INSTANCE_B = "ginst_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

function observation(
  authority: unknown,
  binding: unknown,
  bindingOwner = "global_projection",
) {
  return {
    binding_owner: bindingOwner,
    authority,
    binding,
  };
}

test("classifier projects every RFC binding-match variant", () => {
  const cases = [
    {
      name: "current",
      input: observation(
        {
          kind: "present",
          goal: { goal_id: "release", goal_instance_id: INSTANCE_A },
        },
        { goal_id: "release", goal_instance_id: INSTANCE_A },
      ),
      expected: {
        schema_version: "loopx_goal_binding_match_v1",
        mode: "observe_only",
        kind: "current",
        binding_owner: "global_projection",
        goal_ref: { goal_id: "release", goal_instance_id: INSTANCE_A },
      },
    },
    {
      name: "legacy_read_only",
      input: observation(
        { kind: "present", goal: { goal_id: "release" } },
        { goal_id: "release" },
        "source_registry",
      ),
      expected: {
        schema_version: "loopx_goal_binding_match_v1",
        mode: "observe_only",
        kind: "legacy_read_only",
        binding_owner: "source_registry",
        goal_ref: { goal_id: "release" },
      },
    },
    {
      name: "missing_goal_instance_id",
      input: observation(
        {
          kind: "present",
          goal: { goal_id: "release", goal_instance_id: INSTANCE_A },
        },
        { goal_id: "release" },
      ),
      expected: {
        schema_version: "loopx_goal_binding_match_v1",
        mode: "observe_only",
        kind: "missing_goal_instance_id",
        binding_owner: "global_projection",
        expected: { goal_id: "release", goal_instance_id: INSTANCE_A },
        observed: { goal_id: "release" },
      },
    },
    {
      name: "goal_instance_mismatch",
      input: observation(
        {
          kind: "present",
          goal: { goal_id: "release", goal_instance_id: INSTANCE_B },
        },
        { goal_id: "release", goal_instance_id: INSTANCE_A },
      ),
      expected: {
        schema_version: "loopx_goal_binding_match_v1",
        mode: "observe_only",
        kind: "goal_instance_mismatch",
        binding_owner: "global_projection",
        mismatch: {
          kind: "different_instance",
          expected: { goal_id: "release", goal_instance_id: INSTANCE_B },
          observed: { goal_id: "release", goal_instance_id: INSTANCE_A },
        },
      },
    },
    {
      name: "goal_not_registered",
      input: observation(
        { kind: "absent" },
        { goal_id: "release", goal_instance_id: INSTANCE_A },
      ),
      expected: {
        schema_version: "loopx_goal_binding_match_v1",
        mode: "observe_only",
        kind: "goal_not_registered",
        binding_owner: "global_projection",
        observed: { goal_id: "release", goal_instance_id: INSTANCE_A },
      },
    },
    {
      name: "resolution_in_progress",
      input: observation(
        { kind: "resolution_in_progress" },
        { goal_id: "release", goal_instance_id: INSTANCE_A },
      ),
      expected: {
        schema_version: "loopx_goal_binding_match_v1",
        mode: "observe_only",
        kind: "resolution_in_progress",
        binding_owner: "global_projection",
        observed: { goal_id: "release", goal_instance_id: INSTANCE_A },
      },
    },
    {
      name: "invalid",
      input: observation(
        { kind: "unavailable", reason: "registry_missing" },
        { goal_id: "release" },
      ),
      expected: {
        schema_version: "loopx_goal_binding_match_v1",
        mode: "observe_only",
        kind: "invalid",
        binding_owner: "global_projection",
        issues: [
          {
            kind: "authority_unavailable",
            reason: "registry_missing",
          },
        ],
      },
    },
  ];

  for (const fixture of cases) {
    assert.deepEqual(
      projectGoalBindingMatch(fixture.input),
      fixture.expected,
      fixture.name,
    );
  }
});

test("stamped binding against a legacy Goal is an instance mismatch", () => {
  assert.deepEqual(
    projectGoalBindingMatch(
      observation(
        { kind: "present", goal: { goal_id: "release" } },
        { goal_id: "release", goal_instance_id: INSTANCE_A },
      ),
    ),
    {
      schema_version: "loopx_goal_binding_match_v1",
      mode: "observe_only",
      kind: "goal_instance_mismatch",
      binding_owner: "global_projection",
      mismatch: {
        kind: "stamped_binding_against_legacy_goal",
        expected: { goal_id: "release" },
        observed: { goal_id: "release", goal_instance_id: INSTANCE_A },
      },
    },
  );
});

test("malformed identity facts take precedence over source state", () => {
  for (const goalInstanceId of [
    null,
    "",
    "ginst_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "ginst_short",
  ]) {
    const result = projectGoalBindingMatch(
      observation(
        { kind: "resolution_in_progress" },
        { goal_id: "release", goal_instance_id: goalInstanceId },
      ),
    );
    assert.equal(result.kind, "invalid");
    assert.deepEqual(result.issues, [
      { kind: "invalid_goal_instance_id", side: "binding" },
    ]);
  }

  const mismatchedGoal = projectGoalBindingMatch(
    observation(
      {
        kind: "present",
        goal: { goal_id: "current", goal_instance_id: INSTANCE_A },
      },
      { goal_id: "retained", goal_instance_id: INSTANCE_A },
    ),
  );
  assert.equal(mismatchedGoal.kind, "invalid");
  assert.deepEqual(mismatchedGoal.issues, [{ kind: "goal_id_mismatch" }]);
});

test("a reused process compares each observation instead of retaining a prior match", () => {
  const retainedProjection = {
    goal_id: "release",
    goal_instance_id: INSTANCE_A,
  };
  const first = projectGoalBindingMatch(
    observation(
      { kind: "present", goal: retainedProjection },
      retainedProjection,
    ),
  );
  const afterRecreation = projectGoalBindingMatch(
    observation(
      {
        kind: "present",
        goal: { goal_id: "release", goal_instance_id: INSTANCE_B },
      },
      retainedProjection,
    ),
  );

  assert.equal(first.kind, "current");
  assert.equal(afterRecreation.kind, "goal_instance_mismatch");
  assert.deepEqual(afterRecreation.mismatch, {
    kind: "different_instance",
    expected: { goal_id: "release", goal_instance_id: INSTANCE_B },
    observed: retainedProjection,
  });
});
