# http_server.py
"""FastAPI HTTP server for run_agent, served by Granian (ASGI).

Two endpoints:
  POST /run_agent        → synchronous; returns when the agent finishes.
  POST /run_agent/stream → streaming NDJSON; one event per line (stub in 14.2,
                           wired to the event generator in Layer 14.3).

SECURITY: bind to 127.0.0.1, never 0.0.0.0. The agent runs arbitrary bash
commands; binding to 0.0.0.0 on a shared network exposes shell execution to
anyone who can reach the port. Only expose this behind authentication and
network controls — see the security model documentation.

Run with:
  granian --interface asgi http_server:app --host 127.0.0.1 --port 8000 --workers 1
"""

import json
import sys

sys.path.insert(0, "src")

from dotenv import load_dotenv  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from agent import run_agent  # noqa: E402

load_dotenv()
app = FastAPI(title="Coding Agent HTTP API")


class RunRequest(BaseModel):
    task: str
    model: str | None = None  # overrides the configured MODEL per request
    max_iterations: int | None = None  # accepted; reserved for a future wiring


@app.post("/run_agent")
async def handle_run(req: RunRequest) -> dict:
    """Run to completion; return status and message count.

    run_agent builds its own messages list and system_prompt per call, so
    concurrent requests do not share history. The model is threaded per request
    so two callers can target different providers without shared mutable state.
    """
    try:
        messages = await run_agent(req.task, model=req.model)
    except Exception as exc:  # noqa: BLE001 — surface failures as a structured body
        return {"status": "error", "error": str(exc)}
    return {"status": "ok", "message_count": len(messages)}


@app.post("/run_agent/stream")
async def handle_stream(req: RunRequest) -> StreamingResponse:
    """Stream NDJSON events as the agent runs.

    Stub for Layer 14.2: run synchronously and emit a single summary event. The
    JSON Event Stream layer (14.3) replaces this with a per-event generator
    driven off the emit() seam.
    """

    async def event_lines():
        messages = await run_agent(req.task, model=req.model)
        yield (
            json.dumps(
                {
                    "type": "agent_end",
                    "total_iterations": sum(
                        1 for m in messages if m.get("role") == "assistant"
                    ),
                    "status": "ok",
                }
            )
            + "\n"
        )

    return StreamingResponse(event_lines(), media_type="application/x-ndjson")
