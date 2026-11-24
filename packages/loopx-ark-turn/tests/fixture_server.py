"""Synthetic stdio tool for the installed adapter's transport tests."""
import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

server = FastMCP("turn-fixture")


@server.tool()
def write_observation(value: int) -> str:
    path = Path("observation.json")
    prior = json.loads(path.read_text()) if path.exists() else {"calls": 0}
    result = {
        "value": value, "calls": prior["calls"] + 1,
        "agent": os.environ["LOOPX_TURN_AGENT_ID"],
        "goal": os.environ["LOOPX_TURN_GOAL_ID"],
        "todo": os.environ["LOOPX_TURN_TODO_ID"],
        "provider_credential_present": "ARK_API_KEY" in os.environ,
    }
    path.write_text(json.dumps(result))
    return json.dumps(result)


if __name__ == "__main__":
    server.run(transport="stdio")
