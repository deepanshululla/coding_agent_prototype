---
sidebar_position: 2
title: RPC Mode
description: How to expose run_agent() over a JSON-RPC or HTTP boundary so other processes can drive the agent programmatically.
---

# RPC Mode

`run_agent` is an async Python function. That's fine when your code and the agent share the same process. When they don't — a browser UI, a polyglot pipeline, a subprocess spawned by another tool — you need a boundary.

RPC mode means wrapping `run_agent` in a thin server so external processes can send tasks and receive responses without importing Python directly.

:::note
RPC mode is a **planned extension**, not part of v1. The current project only supports the CLI (`uv run main.py "..."`) and direct library calls described in [Using the Agent as a Library](./sdk.md). This page documents the design so you can add it yourself or track it as a future feature.
:::

## Two approaches

### Approach A — stdin/stdout JSON-RPC (subprocess model)

The simplest boundary is a process that reads a JSON request from stdin, calls `run_agent`, and writes a JSON response to stdout before exiting. The caller spawns a new process per task.

```
┌─────────────┐   JSON on stdin    ┌──────────────────────┐
│  Caller     │ ────────────────►  │  python rpc_server.py│
│  (any lang) │ ◄────────────────  │  → run_agent(task)   │
└─────────────┘   JSON on stdout   └──────────────────────┘
```

Request shape (one JSON object on stdin, newline-terminated):

```json
{
  "jsonrpc": "2.0",
  "id": "req-1",
  "method": "run_agent",
  "params": {
    "task": "List all Python files and count lines of code."
  }
}
```

Response shape (written to stdout after `run_agent` returns):

```json
{
  "jsonrpc": "2.0",
  "id": "req-1",
  "result": {
    "status": "ok"
  }
}
```

In v1, the agent's output goes to the subprocess's stdout interleaved with the response. A cleaner design emits [JSON events](./json-event-stream.md) on stdout and reserves stderr for errors, then writes the final JSON-RPC response at the end.

Minimal skeleton:

```python
# rpc_server.py  (planned, not in v1)
import asyncio
import json
import sys
from dotenv import load_dotenv

sys.path.insert(0, "src")
from agent import run_agent

async def main():
    load_dotenv()
    raw = sys.stdin.readline()
    request = json.loads(raw)

    task = request["params"]["task"]
    req_id = request.get("id")

    try:
        await run_agent(task)
        response = {"jsonrpc": "2.0", "id": req_id, "result": {"status": "ok"}}
    except Exception as e:
        response = {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32000, "message": str(e)},
        }

    print(json.dumps(response), flush=True)

asyncio.run(main())
```

### Approach B — HTTP server (FastAPI + Granian)

When you need a real **network** boundary — a browser UI, a remote caller, multiple clients —
serve `run_agent` over HTTP. Two pieces at two layers:

- **FastAPI** — the *framework*: routing, request/response validation, and a
  `StreamingResponse` for the event stream.
- **[Granian](https://github.com/emmett-framework/granian)** — the *ASGI server* that runs the
  app. A Rust-based server (HTTP/1 + HTTP/2, single binary, no gunicorn+worker glue) that runs
  the FastAPI app directly. It replaces uvicorn; it does **not** replace FastAPI.

```
┌─────────────┐   POST /run_agent   ┌───────────────────────────────┐
│  HTTP client│ ─────────────────►  │  Granian (ASGI)  →  FastAPI    │
│             │ ◄─────────────────  │            →  run_agent(task)  │
└─────────────┘   JSON / NDJSON     └───────────────────────────────┘
```

Two endpoints: one synchronous (returns when the run finishes), one streaming (emits
[JSON events](./json-event-stream.md) as they happen).

```python
# http_server.py  (planned, not in v1)
import sys
sys.path.insert(0, "src")

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from agent import run_agent

load_dotenv()
app = FastAPI()


class RunRequest(BaseModel):
    task: str
    model: str | None = None        # override MODEL per request
    max_iterations: int | None = None


@app.post("/run_agent")
async def handle_run(req: RunRequest):
    """Synchronous: run to completion, return the final message history."""
    messages = await run_agent(req.task)
    return {"status": "ok", "messages": messages}


@app.post("/run_agent/stream")
async def handle_stream(req: RunRequest):
    """Streaming: NDJSON, one JSON event per line as the loop produces them.

    Requires the emit()/event-queue seam from the JSON Event Stream page so the
    loop pushes events to a per-request asyncio.Queue instead of printing.
    """
    async def events():
        async for event in run_agent_events(req.task):   # see json-event-stream.md
            yield event.to_json() + "\n"
    return StreamingResponse(events(), media_type="application/x-ndjson")
```

Run it with Granian:

```bash
uv add fastapi granian
granian --interface asgi http_server:app \
  --host "${AGENT_HTTP_HOST:-127.0.0.1}" \
  --port "${AGENT_HTTP_PORT:-8000}" \
  --workers 1
```

Granian also has a Python entrypoint if you'd rather launch from code:

```python
from granian import Granian

Granian("http_server:app", interface="asgi",
        address="127.0.0.1", port=8000).serve()
```

:::warning Don't capture stdout per request
A shared `redirect_stdout` buffer is not safe across concurrent requests — they'd interleave.
Return the message history (synchronous) or per-request **event queues**
([JSON Event Stream](./json-event-stream.md)) instead of scraping a global stdout. This is the
main thing to get right when serving the agent.
:::

:::tip Default to 127.0.0.1
The agent runs arbitrary `bash`. Bind to `127.0.0.1` (localhost) unless you have put auth and
network controls in front of it — see [Security Model](../operations/security.md). `0.0.0.0`
on a shared network exposes shell execution to anyone who can reach the port.
:::

## Request / response schema

| Field | Type | Description |
|-------|------|-------------|
| `task` | string | Natural-language task for the agent |
| `model` | string (optional) | LiteLLM model string — overrides `MODEL` in `provider.py` |
| `cwd` | string (optional) | Working directory passed to `build_system_prompt()` |
| `max_iterations` | int (optional) | Override `MAX_ITERATIONS` (default 30) |

Response:

| Field | Type | Description |
|-------|------|-------------|
| `status` | `"ok"` or `"error"` | Whether `run_agent` completed without exception |
| `output` | string (optional) | Captured stdout text — only if the server wires up capture |
| `error` | string (optional) | Exception message, present when `status == "error"` |

For richer streaming responses (text deltas, tool events), replace `output` with a stream of JSON events as described in [JSON Event Stream Mode](./json-event-stream.md).

## Concurrency considerations

`run_agent` is a single-tenant loop: it uses one shared `messages` list and one `system_prompt`. Two concurrent calls would corrupt each other's history. Options:

- **Process-per-request** (stdin/stdout model): isolation is free; overhead is one Python startup per task.
- **Task isolation in the HTTP model**: `run_agent` already builds its own `messages` and `system_prompt` locals per call, so concurrent requests don't share history. The unsafe part is the global `MODEL` string in `provider.py` — make it a per-request parameter (the `model` field above) instead of a module constant.
- **Granian workers**: scale out with `granian --workers N` to run N OS processes, each handling requests on its own event loop. Because each agent run also fires off blocking tool work (`bash`, file I/O) via `asyncio.to_thread`, a small worker count plus the thread pool usually saturates CPU before connection multiplexing becomes the bottleneck. Put a reverse proxy in front only when you outgrow a single host.

## Related pages

- [Using the Agent as a Library](./sdk.md) — calling `run_agent` from the same process
- [JSON Event Stream Mode](./json-event-stream.md) — structured event output for streaming clients
- [The Agent Loop](../architecture/the-agent-loop.md) — what `run_agent` does internally
