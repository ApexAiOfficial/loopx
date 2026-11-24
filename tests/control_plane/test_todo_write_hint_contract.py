"""Authoring examples use structured arguments, without promising eligibility."""
import shlex

from loopx.control_plane.todos.write_hint import build_todo_write_hint


def test_agent_template_separates_priority_from_text():
    hint = build_todo_write_hint("fixture-goal")
    argv = shlex.split(hint["agent_todo_command_template"])
    assert argv[argv.index("--priority") + 1] == "P1"
    assert argv[argv.index("--text") + 1] == "<agent action>"
    assert "--priority" not in hint["user_gate_command_template"]
    assert "--priority" not in hint["user_action_command_template"]
