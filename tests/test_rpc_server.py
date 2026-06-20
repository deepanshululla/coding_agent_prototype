"""BDD gate for Phase 14.2 — RPC Mode.

Scenario: JSON-RPC request on stdin runs the agent and returns a structured response
  Given rpc_server.py exists at the repo root
  And stream_response is mocked to return a single stop chunk with text "hello"
  When a valid JSON-RPC 2.0 request is written to rpc_server.py's stdin
  Then the process exits with code 0
  And stdout contains exactly one line of valid JSON
  And the JSON has "jsonrpc" equal to "2.0"
  And the JSON has "result.status" equal to "ok"
  And "result.message_count" is a positive integer

The mock (MOCK_AGENT=1) swaps stream_response for a scripted single "hello"
turn, so no real API call is made and the test runs offline.
"""

import json
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.integration
def test_rpc_server_returns_ok():
    """Drive rpc_server.py via subprocess with a mocked agent."""
    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "t-1",
            "method": "run_agent",
            "params": {"task": "say hello"},
        }
    )

    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "rpc_server.py")],
        input=request + "\n",
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "AGENT_UI": "none",
            "MOCK_AGENT": "1",
        },
        cwd=REPO_ROOT,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected one JSON line, got: {result.stdout!r}"

    response = json.loads(lines[0])
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "t-1"
    assert response["result"]["status"] == "ok"
    assert isinstance(response["result"]["message_count"], int)
    assert response["result"]["message_count"] > 0
