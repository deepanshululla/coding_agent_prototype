# rpc_server.py
"""Minimal stdin/stdout JSON-RPC server for run_agent.

Protocol: read one JSON-RPC 2.0 request from stdin, call run_agent, write one
JSON-RPC 2.0 response to stdout, then exit. Agent output goes to the active
renderer (use AGENT_UI=none so it stays off stdout) so it does not corrupt the
single-line JSON response on the stdout channel.

Run it:
    echo '{"jsonrpc":"2.0","id":"1","method":"run_agent",
           "params":{"task":"say hello"}}' \\
      | AGENT_UI=none uv run rpc_server.py

Set MOCK_AGENT=1 to replace the model with a scripted single "hello" turn — no
real API call is made. This is what the subprocess test uses.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, "src")

from dotenv import load_dotenv  # noqa: E402


def _install_mock_agent() -> None:
    """Replace the agent's stream_response with a scripted single-turn LLM.

    run_agent does `from provider import stream_response`, binding the name into
    the agent module's namespace, so patch agent.stream_response (not just
    provider's). The scripted turn yields one text chunk "hello" and a stop, so
    the loop ends after one iteration with no tool calls — no API key needed.
    """
    import agent
    from provider import _chunk

    async def _scripted(messages, system_prompt, model=None):
        yield _chunk(content="hello")
        yield _chunk(finish_reason="stop")

    agent.stream_response = _scripted


async def main() -> None:
    load_dotenv()

    if os.environ.get("MOCK_AGENT") == "1":
        _install_mock_agent()

    from agent import run_agent

    raw = sys.stdin.readline()
    if not raw.strip():
        sys.exit(0)

    request = json.loads(raw)
    req_id = request.get("id")
    task = request.get("params", {}).get("task", "")

    try:
        messages = await run_agent(task)
        response: dict = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "status": "ok",
                "message_count": len(messages),
            },
        }
    except Exception as exc:  # noqa: BLE001 — any failure becomes a JSON-RPC error
        response = {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32000, "message": str(exc)},
        }

    # Write the JSON-RPC response on stdout; keep it on one line.
    print(json.dumps(response), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
