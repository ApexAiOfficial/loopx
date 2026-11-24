import assert from "node:assert/strict";
import test from "node:test";

import {
  deriveCoordinationTodoSuccessorProposals,
  evaluateCoordinationTodoSuccessorDerivation,
  TODO_SUCCESSOR_DERIVATION_REQUEST_SCHEMA,
  TODO_SUCCESSOR_DERIVATION_RESULT_SCHEMA,
} from "../../loopx/control_plane/coordination/todo_successor_derivation.ts";

const predecessor = {
  todo_id: "todo-predecessor",
  role: "agent",
  status: "open",
  text: "[P1] Finish the authority transition",
  task_class: "advancement_task",
  claimed_by: "agent-a",
  capability_binding_ref: "binding-a",
  unblocks_todo_id: "todo-parent",
};

test("complete derives priority, authority bindings, exclusions, and predecessor relation once", () => {
  const input = {
    schema_version: TODO_SUCCESSOR_DERIVATION_REQUEST_SCHEMA,
    command: "complete" as const,
    predecessor,
    registered_agents: ["agent-a", "agent-b", "agent-c"],
    actor_agent_id: "agent-a",
    completion_policy: {
      effective_claimed_by: "agent-a",
      effective_next_claimed_by: "agent-b",
      effective_next_excluded_agents: ["agent-c"],
    },
    successor_intents: [
      {
        role: "agent",
        text: "Continue the provider migration",
        action_kind: "\u0085IMPLEMENTATION\u0085",
        required_capabilities: ["authority_write"],
        continuation_policy: "\u0085INDEPENDENT_HANDOFF\u0085",
      },
      {
        role: "user",
        text: "Approve the resulting authority boundary",
        task_class: "user_gate",
      },
    ],
  };

  const proposals = deriveCoordinationTodoSuccessorProposals(input);
  assert.deepEqual(proposals, [
    {
      role: "agent",
      text: "[P1] Continue the provider migration",
      task_class: "advancement_task",
      created_by: "agent-a",
      action_kind: "implementation",
      capability_binding_ref: "binding-a",
      required_capabilities: ["authority_write"],
      continuation_policy: "independent_handoff",
      claimed_by: "agent-b",
      excluded_agents: ["agent-c"],
      unblocks_todo_id: "todo-predecessor",
    },
    {
      role: "user",
      text: "[P1] Approve the resulting authority boundary",
      task_class: "user_gate",
      created_by: "agent-a",
      bound_agent: "agent-a",
      blocks_agent: "agent-a",
      action_kind: "gate",
    },
  ]);
  assert.equal(input.successor_intents[0]!.text, "Continue the provider migration");
});

test("supersede inherits same-agent continuity, binding, and existing unblock relation", () => {
  const proposals = deriveCoordinationTodoSuccessorProposals({
    schema_version: TODO_SUCCESSOR_DERIVATION_REQUEST_SCHEMA,
    command: "supersede",
    predecessor,
    registered_agents: ["agent-a", "agent-b"],
    actor_agent_id: "agent-b",
    completion_policy: null,
    successor_intents: [
      {
        role: "agent",
        text: "[P0] Replace the failed implementation",
        task_class: "blocker",
        continuation_policy: "same_agent_non_delivery",
        excluded_agents: ["agent-b"],
      },
      {
        role: "user",
        text: "Confirm the replacement",
        task_class: "user_action",
      },
    ],
  });

  assert.deepEqual(proposals[0], {
    role: "agent",
    text: "[P0] Replace the failed implementation",
    task_class: "blocker",
    created_by: "agent-b",
    capability_binding_ref: "binding-a",
    continuation_policy: "same_agent_non_delivery",
    claimed_by: "agent-a",
    excluded_agents: ["agent-b"],
    unblocks_todo_id: "todo-parent",
  });
  assert.deepEqual(proposals[1], {
    role: "user",
    text: "[P1] Confirm the replacement",
    task_class: "user_action",
    created_by: "agent-b",
    bound_agent: "agent-a",
  });
});

test("empty intent is identity and skips successor-only authority validation", () => {
  const result = evaluateCoordinationTodoSuccessorDerivation({
    schema_version: TODO_SUCCESSOR_DERIVATION_REQUEST_SCHEMA,
    command: "complete",
    predecessor,
    registered_agents: [],
    actor_agent_id: "legacy-unregistered-agent",
    completion_policy: {},
    successor_intents: [],
  });

  assert.deepEqual(result, {
    schema_version: TODO_SUCCESSOR_DERIVATION_RESULT_SCHEMA,
    status: "derived",
    successors: [],
  });
});

test("derivation fails closed for contradictory or malformed caller intent", () => {
  const result = evaluateCoordinationTodoSuccessorDerivation({
    schema_version: TODO_SUCCESSOR_DERIVATION_REQUEST_SCHEMA,
    command: "complete",
    predecessor,
    registered_agents: ["agent-a", "agent-b"],
    actor_agent_id: "agent-a",
    completion_policy: {
      effective_claimed_by: "agent-a",
      effective_next_claimed_by: "agent-b",
      effective_next_excluded_agents: ["agent-b"],
    },
    successor_intents: [{
      role: "agent",
      text: "Continue",
      task_class: "advancement_task",
    }],
  });

  assert.equal(result.schema_version, TODO_SUCCESSOR_DERIVATION_RESULT_SCHEMA);
  assert.equal(result.status, "failed");
  assert.equal(result.reason_code, "invalid_todo_successor_derivation");
  assert.match(String(result.reason), /claimed_by cannot also appear in excluded_agents/u);

  const missingText = evaluateCoordinationTodoSuccessorDerivation({
    schema_version: TODO_SUCCESSOR_DERIVATION_REQUEST_SCHEMA,
    command: "supersede",
    predecessor,
    registered_agents: ["agent-a"],
    actor_agent_id: "agent-a",
    completion_policy: null,
    successor_intents: [{role: "agent", text: "", claimed_by: "agent-a"}],
  });
  assert.equal(missingText.status, "failed");
  assert.match(String(missingText.reason), /text must not be empty/u);
});
