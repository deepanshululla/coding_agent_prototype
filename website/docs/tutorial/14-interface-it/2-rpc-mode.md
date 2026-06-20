---
sidebar_position: 2
title: "Layer 14.2 — RPC Mode"
description: Wrap run_agent() in a stdin/stdout JSON-RPC loop (default) or a FastAPI-on-Granian HTTP server so processes in any language can drive the agent over a network boundary.
---

# Layer 14.2 — RPC Mode

:::note Starting point
Layer 14.1 complete: `src/sdk.py` exists and `run_agent_collecting()` gathers typed events from the emit() seam alongside the message history.
:::

`run_agent` is an async Python function. That's fine when your driver code shares the same Python process. When it doesn't — a browser UI, a polyglot pipeline, a CI orchestrator written in Go or Node — you need a boundary. RPC mode wraps `run_agent` in a thin server so external processes can send tasks and receive responses without importing Python at all.

Two approaches are documented in [RPC Mode](../../programmatic-usage/rpc-mode.md). This layer implements both and verifies the simpler one with a BDD gate.

## What you'll learn

- How to build a minimal stdin/stdout JSON-RPC server that processes one request and exits.
- How to wire FastAPI + Granian as an HTTP option for multi-client, persistent deployments.
- Why concurrent request isolation matters and how `run_agent`'s local state already provides it.
- Which safety constraint to respect when binding the HTTP server.

## Build it

### Step 1 — stdin/stdout JSON-RPC server

The simplest process boundary: read one JSON request from stdin, run the agent, write one JSON response to stdout. The caller spawns a subprocess per task and communicates over pipes.

```
┌────────────────┐   JSON on stdin    ┌─────────────────────────┐
│  Caller        │ ────────────────►  │  python rpc_server.py   │
│  (any language)│ ◄────────────────  │  → run_agent(task)      │
└────────────────┘   JSON on stdout   └─────────────────────────┘
```

Create `rpc_server.py` at the repo root:

```python
# rpc_server.py
"""Minimal stdin/stdout JSON-RPC server for run_agent.

Protocol: read one JSON-RPC 2.0 request from stdin, call run_agent,
write one JSON-RPC 2.0 response to stdout. Agent output goes to stderr
(or the active renderer) so it does not corrupt the response channel.
"""

import asyncio
import json
import sys

sys.path.insert(0, "src")

from dotenv import load_dotenv
from agent import run_agent


async def main() -> None:
    load_dotenv()

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
    except Exception as exc:
        response = {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32000, "message": str(exc)},
        }

    # Write the JSON-RPC response on stdout; keep it on one line.
    print(json.dumps(response), flush=True)


asyncio.run(main())
```

:::tip Why separate stdout from agent output?
In v1 the agent prints to stdout, which would corrupt the JSON response channel. Set `AGENT_UI=none` (or redirect agent output to stderr) when using the RPC server. The [JSON Event Stream](./3-json-event-stream.md) layer shows the clean design: emit NDJSON events on stdout *before* the final JSON-RPC response, all on one channel.
:::

Call it from any language. From a shell:

```bash
echo '{"jsonrpc":"2.0","id":"req-1","method":"run_agent","params":{"task":"say hello"}}' \
  | AGENT_UI=none uv run rpc_server.py
# → {"jsonrpc": "2.0", "id": "req-1", "result": {"status": "ok", "message_count": 3}}
```

From Python (as a subprocess):

```python
import subprocess
import json
import os

request = json.dumps({
    "jsonrpc": "2.0",
    "id": "req-1",
    "method": "run_agent",
    "params": {"task": "list the files in src/"},
})

proc = subprocess.run(
    ["uv", "run", "rpc_server.py"],
    input=request + "\n",
    capture_output=True,
    text=True,
    env={**os.environ, "AGENT_UI": "none"},
)

response = json.loads(proc.stdout)
print(response["result"])
```

### Step 2 — HTTP server (FastAPI + Granian)

For a **persistent network boundary** — a browser frontend, multiple concurrent callers, or a remote deployment — serve `run_agent` over HTTP. Install the dependencies:

```bash
uv add fastapi granian
```

Create `http_server.py` at the repo root:

```python
# http_server.py
"""FastAPI HTTP server for run_agent, served by Granian (ASGI).

Two endpoints:
  POST /run_agent        → synchronous; returns when the agent finishes.
  POST /run_agent/stream → streaming NDJSON; one event per line.

Run with:
  granian --interface asgi http_server:app --host 127.0.0.1 --port 8000 --workers 1
"""

import sys
sys.path.insert(0, "src")

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent import run_agent

load_dotenv()
app = FastAPI(title="Coding Agent HTTP API")


class RunRequest(BaseModel):
    task: str
    model: str | None = None          # overrides MODEL env var per request
    max_iterations: int | None = None  # overrides MAX_ITERATIONS


@app.post("/run_agent")
async def handle_run(req: RunRequest) -> dict:
    """Run to completion; return status and message count."""
    messages = await run_agent(req.task)
    return {"status": "ok", "message_count": len(messages)}


@app.post("/run_agent/stream")
async def handle_stream(req: RunRequest) -> StreamingResponse:
    """Stream NDJSON events as the agent runs.

    Requires the run_agent_events() generator from the JSON Event Stream
    layer — see ./3-json-event-stream.md.
    """
    import json

    async def event_lines():
        # Placeholder: import run_agent_events once Layer 14.3 is complete.
        # For now, run synchronously and emit a single summary event.
        messages = await run_agent(req.task)
        yield json.dumps({
            "type": "agent_end",
            "total_iterations": sum(
                1 for m in messages if m.get("role") == "assistant"
            ),
            "status": "ok",
        }) + "\n"

    return StreamingResponse(event_lines(), media_type="application/x-ndjson")
```

:::warning Bind to 127.0.0.1, not 0.0.0.0
The agent runs arbitrary `bash` commands. Binding to `0.0.0.0` on a shared network exposes shell execution to anyone who can reach the port. Always bind to `127.0.0.1` (localhost) unless you have authentication and network controls in place — see the security model documentation.
:::

Start the server:

```bash
granian --interface asgi http_server:app \
  --host 127.0.0.1 \
  --port 8000 \
  --workers 1
```

Call it:

```bash
curl -s -X POST http://127.0.0.1:8000/run_agent \
  -H "Content-Type: application/json" \
  -d '{"task": "list the files in src/"}'
# → {"status": "ok", "message_count": 5}
```

### Step 3 — Request/response schema

| Request field | Type | Description |
|---------------|------|-------------|
| `task` | string | Natural-language task for the agent |
| `model` | string (optional) | LiteLLM model string — overrides `MODEL` in `provider.py` |
| `max_iterations` | int (optional) | Override `MAX_ITERATIONS` (default 30) |

| Response field | Type | Description |
|----------------|------|-------------|
| `status` | `"ok"` or `"error"` | Whether `run_agent` completed without exception |
| `message_count` | int | Number of messages in the final history |
| `error` | string (optional) | Exception message when `status == "error"` |

For streaming responses with per-event granularity, see [Layer 14.3 — JSON Event Stream](./3-json-event-stream.md).

### Step 4 — Concurrency note

`run_agent` builds its own `messages` list and `system_prompt` locals per call, so concurrent HTTP requests do not share history. The only shared mutable state is the global `MODEL` string in `provider.py` — make it a per-request parameter (the `model` field above) to make concurrent calls fully independent.

The stdin/stdout model gives process-level isolation for free: each subprocess has its own Python runtime. Scale the HTTP model with `granian --workers N` to run N OS processes, each with its own event loop.

## Test it

### Behavior (BDD)

Verify this layer as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Scenario: JSON-RPC request on stdin runs the agent and returns a structured response
  Given rpc_server.py exists at the repo root
  And stream_response is mocked to return a single stop chunk with text "hello"
  When a valid JSON-RPC 2.0 request is written to rpc_server.py's stdin
  Then the process exits with code 0
  And stdout contains exactly one line of valid JSON
  And the JSON has "jsonrpc" equal to "2.0"
  And the JSON has "result.status" equal to "ok"
  And "result.message_count" is a positive integer
```

Run this as an integration scenario with the [BDD framework](../../guides/bdd-integration-testing.md).

The scenario fails before `rpc_server.py` exists because the subprocess invocation raises `FileNotFoundError`. After the build it passes because the server reads the request, runs the (mocked) agent, and writes the JSON response.

### Subprocess test

Add a test in `tests/test_rpc_server.py`:

```python
import json
import os
import subprocess
import sys
import pytest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.integration
def test_rpc_server_returns_ok(monkeypatch, tmp_path):
    """Drive rpc_server.py via subprocess with a mocked agent."""
    request = json.dumps({
        "jsonrpc": "2.0",
        "id": "t-1",
        "method": "run_agent",
        "params": {"task": "say hello"},
    })

    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "rpc_server.py")],
        input=request + "\n",
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "AGENT_UI": "none",
            # Point at the mock model so no real API call is made:
            "MOCK_AGENT": "1",
        },
        cwd=REPO_ROOT,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout.strip())
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "t-1"
    assert response["result"]["status"] == "ok"
    assert response["result"]["message_count"] > 0
```

```bash
uv run pytest tests/test_rpc_server.py -v -m integration
```

## Run it

```bash
# stdin/stdout JSON-RPC (one request, then exit)
echo '{"jsonrpc":"2.0","id":"1","method":"run_agent","params":{"task":"say hello"}}' \
  | AGENT_UI=none uv run rpc_server.py

# HTTP server (persistent, listens for requests)
granian --interface asgi http_server:app --host 127.0.0.1 --port 8000 --workers 1 &

curl -s -X POST http://127.0.0.1:8000/run_agent \
  -H "Content-Type: application/json" \
  -d '{"task": "echo hello from HTTP"}'
```

## Recap

The agent now has two process-boundary interfaces: a one-shot stdin/stdout JSON-RPC server and a persistent FastAPI-on-Granian HTTP server. Both call the same `run_agent` function; the boundary is purely in the transport layer.

The HTTP streaming endpoint is a stub right now. The next layer adds the NDJSON event emitter that makes it real — and that also makes log pipelines and dashboards possible.

→ [Layer 14.3 — JSON Event Stream](./3-json-event-stream.md)
