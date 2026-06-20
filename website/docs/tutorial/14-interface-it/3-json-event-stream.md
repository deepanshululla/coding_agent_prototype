---
sidebar_position: 3
title: "Layer 14.3 — JSON Event Stream"
description: Emit each agent loop phase as a newline-delimited JSON event so log pipelines, dashboards, and streaming HTTP clients can consume structured output without parsing human-readable text.
---

# Layer 14.3 — JSON Event Stream

:::note Implemented
This step is implemented on branch `step/phase-14-3-json-event-stream` (plan: `plans/tutorial/phase-14-3-json-event-stream.md`).
:::

:::note Starting point
Layer 14.2 complete: `rpc_server.py` and `http_server.py` exist. The HTTP streaming endpoint in `http_server.py` is a stub — it emits only a single `agent_end` event. The emit() seam from Phase 10 fires events but routes them to the active renderer, not to the network.
:::

The agent already emits typed events through the `emit()` seam: `text_delta`, `tool_call_start`, `tool_call_end`, `turn_end`, `agent_end`. Right now those events flow to a renderer (stdout text or the TUI). This layer adds a second output path: newline-delimited JSON (NDJSON) on stdout, controlled by `AGENT_OUTPUT=json`.

One JSON object per line. One `json.loads` per event. No parser state. That's the format that log pipelines, dashboards, and streaming HTTP clients expect.

The event schema and wire format are documented in [JSON Event Stream Mode](../../programmatic-usage/json-event-stream.md). This page is the build step.

## What you'll learn

- How to add an `AGENT_OUTPUT=json` mode to the existing `renderer.py` selector so NDJSON output is opt-in.
- How to wire the NDJSON emitter into the HTTP streaming endpoint from Layer 14.2.
- How to consume the stream with `jq` to verify event ordering.
- Why NDJSON is preferable to line-buffered plain text for programmatic consumers.

## Build it

### Step 1 — Add the NDJSON emitter to `renderer.py`

The renderer selector already picks between `stdout` and `tui` via `AGENT_UI`. Add a second env var, `AGENT_OUTPUT`, that switches the emit function from human-readable lines to JSON objects:

```python
# src/renderer.py  (updated)

"""Selects the active renderer based on AGENT_UI and AGENT_OUTPUT.

AGENT_UI controls which human renderer is active:
  stdout  (default) — plain-text stdout, byte-for-byte backward compatible
  tui                — Textual terminal UI (Layer 10.2)
  none               — suppress all output (useful for RPC mode)

AGENT_OUTPUT controls the wire format:
  (unset, default)  — human-readable via the active AGENT_UI renderer
  json              — NDJSON: one JSON object per line on stdout
"""

import json as _json
import os
import sys

_OUTPUT = os.getenv("AGENT_OUTPUT", "")
_UI = os.getenv("AGENT_UI", "stdout")


if _OUTPUT == "json":
    def emit(event: dict) -> None:
        print(_json.dumps(event), flush=True)

elif _UI == "tui":
    from tui.emit import emit  # noqa: F401 — populated in Layer 10.2

elif _UI == "none":
    def emit(event: dict) -> None:  # type: ignore[misc]
        pass

else:
    from renderer_stdout import emit  # noqa: F401
```

That's the entire change to `renderer.py`. No modifications to `agent.py` — the loop already calls `emit()` for every event.

### Step 2 — Verify the event schema

Run the agent with `AGENT_OUTPUT=json` and confirm NDJSON arrives on stdout:

```bash
AGENT_OUTPUT=json uv run main.py "list the files in src/"
```

Each line is a complete JSON object:

```json
{"type": "text_delta", "delta": "I'll list the files"}
{"type": "tool_call_start", "index": 0, "tool_call_id": "call_abc", "name": "list_dir"}
{"type": "tool_call_end", "index": 0, "tool_call_id": "call_abc", "name": "list_dir", "content": "agent.py\ntools.py\n...", "is_error": false, "chars": 42}
{"type": "turn_end", "iteration": 1, "finish_reason": "tool_calls", "tool_calls_count": 1}
{"type": "text_delta", "delta": "Here are the files:"}
{"type": "turn_end", "iteration": 2, "finish_reason": "stop", "tool_calls_count": 0}
{"type": "agent_end", "total_iterations": 2, "status": "ok"}
```

The events arrive in this strict order per iteration:

```
[text_delta ×N]
[tool_call_start ×M]          ← during Phase A (streaming)
[tool_call_end ×M]            ← during Phase D (execution, concurrent)
turn_end                      ← end of inner loop iteration
...repeat for next iteration...
agent_end                     ← when the outer loop exits
```

### Step 3 — Wire the streaming HTTP endpoint

Update the `/run_agent/stream` endpoint in `http_server.py` to use `run_agent_collecting` from `sdk.py` and emit each collected event as an NDJSON line:

```python
# http_server.py  (updated /run_agent/stream endpoint)

import json
import sys
sys.path.insert(0, "src")

from sdk import run_agent_collecting  # Layer 14.1
from fastapi.responses import StreamingResponse


@app.post("/run_agent/stream")
async def handle_stream(req: RunRequest) -> StreamingResponse:
    """NDJSON: one event line per agent loop phase, as they happen."""

    async def event_lines():
        # run_agent_collecting calls run_agent and collects events in order.
        # For true streaming (events before agent_end), use an asyncio.Queue
        # wired into the emit seam — see the architecture note below.
        events, _ = await run_agent_collecting(req.task)
        for event in events:
            yield json.dumps(event) + "\n"

    return StreamingResponse(event_lines(), media_type="application/x-ndjson")
```

:::note True streaming vs. collect-then-flush
The snippet above collects all events and flushes them after the agent finishes — simple, but the client sees nothing until the run completes. For genuine streaming (events arrive at the client in real time), wire an `asyncio.Queue` into the emit seam and yield from it while `run_agent` runs concurrently. The queue pattern is the same one used in Phase 10's TUI renderer. This tutorial defers that to [Phase 15 — Steering](../15-steering.md), where the queue becomes necessary for injecting follow-up messages mid-run.
:::

### Step 4 — Consume the stream with `jq`

`jq` is the fastest way to inspect and filter the event stream:

```bash
# Show all event types in arrival order
AGENT_OUTPUT=json uv run main.py "count lines in tools.py" \
  | jq -r '.type'

# Show only tool events
AGENT_OUTPUT=json uv run main.py "count lines in tools.py" \
  | jq 'select(.type | startswith("tool_call"))'

# Show text reconstruction (all deltas joined)
AGENT_OUTPUT=json uv run main.py "say hello in three words" \
  | jq -r 'select(.type == "text_delta") | .delta' \
  | tr -d '\n'

# Pretty-print agent_end summary
AGENT_OUTPUT=json uv run main.py "list src/" \
  | jq 'select(.type == "agent_end")'
```

Expected output for the type-listing command (a two-iteration run with one tool call):

```
text_delta
tool_call_start
tool_call_end
turn_end
text_delta
turn_end
agent_end
```

### Step 5 — Python consumer (subprocess)

```python
import subprocess
import json
import os
import sys

proc = subprocess.Popen(
    ["uv", "run", "main.py", "list all .py files in src/"],
    stdout=subprocess.PIPE,
    env={**os.environ, "AGENT_OUTPUT": "json"},
    text=True,
)

text_buf = ""
tool_calls_seen = []

for line in proc.stdout:
    event = json.loads(line)
    t = event["type"]

    if t == "text_delta":
        text_buf += event["delta"]
    elif t == "tool_call_end":
        tool_calls_seen.append(event["name"])
        if event["is_error"]:
            print(f"[TOOL ERROR] {event['name']}: {event['content']}", file=sys.stderr)
    elif t == "agent_end":
        print(f"Done in {event['total_iterations']} iterations")
        print(f"Tools used: {tool_calls_seen}")
        print(f"Text output: {text_buf[:200]}")
```

## Test it

### Behavior (BDD)

Verify this layer as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Scenario: Piping AGENT_OUTPUT=json through jq shows all event types in order
  Given AGENT_OUTPUT=json is set in the environment
  And stream_response is mocked to return a stop chunk with text and one tool call
  When the agent is run and its stdout is captured line by line
  Then each line is a valid JSON object (json.loads succeeds)
  And the event types appear in this order:
       text_delta, tool_call_start, tool_call_end, turn_end, text_delta, turn_end, agent_end
  And no text_delta event appears after the agent_end event
  And the tool_call_start event is immediately followed (with possible text_deltas)
       by a tool_call_end event with the same tool_call_id
```

Run this as an integration scenario with the [BDD framework](../../guides/bdd-integration-testing.md).

The scenario fails before the NDJSON emitter is added to `renderer.py` because `AGENT_OUTPUT=json` has no effect — `renderer.py` falls through to the human-readable stdout emitter, producing non-JSON lines that make `json.loads` raise `JSONDecodeError`. After the build it passes because each line is a well-formed JSON object and the type sequence matches.

### Unit test

Add a test in `tests/test_json_event_stream.py`:

```python
import asyncio
import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import sys

sys.path.insert(0, "src")


def make_chunk(text=None, tool_name=None, tool_id=None, tool_idx=0,
               tool_args=None, finish="stop"):
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    delta = chunk.choices[0].delta
    delta.content = text
    delta.tool_calls = None
    chunk.choices[0].finish_reason = finish
    if tool_name:
        tc = MagicMock()
        tc.index = tool_idx
        tc.id = tool_id
        tc.function.name = tool_name
        tc.function.arguments = tool_args or "{}"
        delta.tool_calls = [tc]
        delta.content = None
        chunk.choices[0].finish_reason = "tool_calls"
    return chunk


async def fake_stream_with_tool(*args, **kwargs):
    yield make_chunk(text="I'll check that.")
    yield make_chunk(tool_name="list_dir", tool_id="call_x", tool_args='{"path":"."}')
    yield make_chunk(finish="stop")  # second call — stop


@pytest.mark.asyncio
@patch("agent.stream_response", side_effect=fake_stream_with_tool)
@patch.dict(os.environ, {"AGENT_OUTPUT": "json"})
async def test_ndjson_event_order(mock_stream, capsys):
    # Re-import renderer so it picks up the patched env var.
    import importlib
    import renderer
    importlib.reload(renderer)

    from sdk import run_agent_collecting
    events, _ = await run_agent_collecting("test")

    types = [e["type"] for e in events]
    assert "text_delta" in types
    assert "tool_call_start" in types
    assert "tool_call_end" in types
    assert "agent_end" in types
    assert types[-1] == "agent_end"

    # tool_call_start must precede its matching tool_call_end
    start_ids = {e["tool_call_id"]: i for i, e in enumerate(events)
                 if e["type"] == "tool_call_start"}
    for i, e in enumerate(events):
        if e["type"] == "tool_call_end":
            tid = e["tool_call_id"]
            assert tid in start_ids, f"tool_call_end for {tid} has no matching start"
            assert start_ids[tid] < i, "tool_call_start must precede tool_call_end"
```

```bash
uv run pytest tests/test_json_event_stream.py -v
```

## Run it

```bash
# NDJSON on stdout — one event per line
AGENT_OUTPUT=json uv run main.py "list the files in src/"

# Filter to tool events only
AGENT_OUTPUT=json uv run main.py "list the files in src/" \
  | jq 'select(.type | startswith("tool_call"))'

# Count text characters across all deltas
AGENT_OUTPUT=json uv run main.py "list the files in src/" \
  | jq '[select(.type == "text_delta") | .delta | length] | add'

# Stream via HTTP (requires http_server.py running on port 8000)
curl -s -X POST http://127.0.0.1:8000/run_agent/stream \
  -H "Content-Type: application/json" \
  -d '{"task": "list the files in src/"}' \
  | jq -r '.type'
```

:::tip Architecture pattern
The event stream is the externally-visible face of an [event-sourced run log](../../architecture-patterns/event-sourcing.md) — the same events, emitted as NDJSON.
:::

## Recap

The `AGENT_OUTPUT=json` mode turns every `emit()` call into a newline-delimited JSON object on stdout. The five event types — `text_delta`, `tool_call_start`, `tool_call_end`, `turn_end`, `agent_end` — arrive in a deterministic order that reflects the agent loop's phases. Any program that can read lines and call `json.loads` can now consume the agent's structured output.

Combined with Layers 14.1 (SDK) and 14.2 (RPC Mode), the agent now has three interface tiers: in-process library, cross-process JSON-RPC, and streaming HTTP. The next phase adds interactive steering — injecting follow-up messages into a running agent without starting a new session.

→ [Phase 15 — Steering](../15-steering.md)
