---
sidebar_position: 3
title: JSON Event Stream Mode
description: Emit each phase of the agent loop as newline-delimited JSON events for programmatic consumers and streaming UIs.
---

# JSON Event Stream Mode

The v1 agent prints everything to stdout as human-readable text: streamed model tokens, tool names as they're invoked, and brief status lines after each tool completes. That's fine at a terminal. It's not useful when another program is consuming the output.

JSON Event Stream mode means replacing those `print()` calls with newline-delimited JSON (NDJSON) — one JSON object per line, each representing a discrete event in the agent loop. A consumer reads the stream and can render a UI, record metrics, or forward events to another service.

:::note
JSON Event Stream mode is a **planned extension**, not part of v1. The current implementation streams plain text to stdout. This page documents the event schema and where in the loop the emitter would be wired, so you can add it as an output mode.
:::

## Why NDJSON

Newline-delimited JSON is the standard format for streaming structured data over stdout or HTTP:

- One `json.loads(line)` per event — no parser state.
- Consumers can filter by `type` and ignore events they don't understand.
- Works over a pipe, a WebSocket, or Server-Sent Events without protocol changes.
- Easy to log and replay.

## Event types

The agent loop has five observable phases. Each maps to an event type.

### `text_delta`

Emitted for each streamed text fragment from the model (during Phase A of the inner loop).

```json
{"type": "text_delta", "delta": "Here is what I found in the file:"}
```

| Field | Type | Description |
|-------|------|-------------|
| `type` | `"text_delta"` | Event discriminator |
| `delta` | string | The text fragment; may be a single character |

In v1, these arrive from `chunk.choices[0].delta.content` during the streaming loop. The emitter replaces `print(delta.content, end="", flush=True)`.

### `tool_call_start`

Emitted when a new tool call index is first seen in the stream — i.e., when `tc_chunk.function.name` arrives for a given `index`.

```json
{
  "type": "tool_call_start",
  "index": 0,
  "tool_call_id": "call_abc123",
  "name": "read_file"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `type` | `"tool_call_start"` | Event discriminator |
| `index` | int | Position in the batch (0-based) |
| `tool_call_id` | string | Unique ID for this call; matches the `tool_call_id` in the result |
| `name` | string | Tool name (e.g. `"read_file"`, `"bash"`) |

### `tool_call_end`

Emitted once per tool call, after `_execute_one_tool` returns (Phase D). Carries the full result.

```json
{
  "type": "tool_call_end",
  "index": 0,
  "tool_call_id": "call_abc123",
  "name": "read_file",
  "content": "1  import asyncio\n2  ...",
  "is_error": false,
  "chars": 1024
}
```

| Field | Type | Description |
|-------|------|-------------|
| `type` | `"tool_call_end"` | Event discriminator |
| `index` | int | Matches the `tool_call_start` index |
| `tool_call_id` | string | Matches the start event |
| `name` | string | Tool name |
| `content` | string | Tool output (or error message) |
| `is_error` | bool | `true` if the tool returned an error |
| `chars` | int | Length of `content` — useful for dashboards |

### `turn_end`

Emitted at the end of each inner-loop iteration — after tool results are pushed to message history (Phase E), or after the `finish_reason == "stop"` check (Phase C).

```json
{
  "type": "turn_end",
  "iteration": 1,
  "finish_reason": "tool_calls",
  "tool_calls_count": 2
}
```

| Field | Type | Description |
|-------|------|-------------|
| `type` | `"turn_end"` | Event discriminator |
| `iteration` | int | Which inner-loop iteration just completed (1-indexed) |
| `finish_reason` | `"stop"` or `"tool_calls"` | The model's finish reason |
| `tool_calls_count` | int | Number of tool calls in this turn (0 for stop turns) |

### `agent_end`

Emitted once, when the outer loop exits.

```json
{
  "type": "agent_end",
  "total_iterations": 4,
  "status": "ok"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `type` | `"agent_end"` | Event discriminator |
| `total_iterations` | int | Total inner-loop iterations across all outer-loop passes |
| `status` | `"ok"` or `"error"` | Whether the agent completed normally |
| `error` | string (optional) | Exception message if `status == "error"` |

## Mapping loop phases to events

```
Phase A: stream chunks
  └── delta.content present      → emit text_delta
  └── tc_chunk.function.name seen → emit tool_call_start

Phase B: append assistant turn   (no event — internal bookkeeping)

Phase C: stop check
  └── finish_reason == "stop"    → emit turn_end(finish_reason="stop")

Phase D: execute tools
  └── each tool returns          → emit tool_call_end

Phase E: push tool results       (no event — internal bookkeeping)
  └── iteration complete         → emit turn_end(finish_reason="tool_calls")

Outer loop exits                 → emit agent_end
```

## Where to wire the emitter

The emitter is a single function that writes to stdout:

```python
import json
import sys

def emit(event: dict) -> None:
    print(json.dumps(event), flush=True)
```

Replace each `print()` call in `agent.py` with an `emit()` call:

```python
# Before (v1 — plain text)
if delta.content:
    text_buf += delta.content
    print(delta.content, end="", flush=True)

if tc_chunk.function and tc_chunk.function.name:
    tool_acc[idx]["name"] = tc_chunk.function.name
    print(f"\n▸ {tc_chunk.function.name}", end="", flush=True)
```

```python
# After (JSON event stream mode)
if delta.content:
    text_buf += delta.content
    emit({"type": "text_delta", "delta": delta.content})

if tc_chunk.function and tc_chunk.function.name:
    tool_acc[idx]["name"] = tc_chunk.function.name
    emit({
        "type": "tool_call_start",
        "index": idx,
        "tool_call_id": tool_acc[idx]["id"],
        "name": tc_chunk.function.name,
    })
```

The `emit` function is the only change needed in `agent.py`. Everything else — streaming accumulation, tool dispatch, message history — stays the same.

## Switching between modes

A simple flag controls which emitter is active:

```python
import os

if os.getenv("AGENT_OUTPUT") == "json":
    def emit(event: dict) -> None:
        print(json.dumps(event), flush=True)
else:
    def emit(event: dict) -> None:
        # reconstruct human-readable output
        t = event["type"]
        if t == "text_delta":
            print(event["delta"], end="", flush=True)
        elif t == "tool_call_start":
            print(f"\n▸ {event['name']}", end="", flush=True)
        elif t == "tool_call_end":
            status = "✓" if not event["is_error"] else "✗"
            print(f"  [{status} {event['name']}: {event['chars']} chars]")
```

Invoke with:

```bash
AGENT_OUTPUT=json uv run main.py "refactor tools.py"
```

## Consuming the stream

A Python consumer reading from a subprocess:

```python
import subprocess
import json

proc = subprocess.Popen(
    ["uv", "run", "main.py", "list all .py files"],
    stdout=subprocess.PIPE,
    env={**os.environ, "AGENT_OUTPUT": "json"},
    text=True,
)

for line in proc.stdout:
    event = json.loads(line)
    if event["type"] == "text_delta":
        print(event["delta"], end="")
    elif event["type"] == "tool_call_end" and event["is_error"]:
        print(f"[TOOL ERROR] {event['name']}: {event['content']}", file=sys.stderr)
    elif event["type"] == "agent_end":
        print(f"\n--- done in {event['total_iterations']} iterations ---")
```

## Related pages

- [Using the Agent as a Library](./sdk.md) — calling `run_agent` from the same process
- [RPC Mode](./rpc-mode.md) — JSON-RPC and HTTP transport for cross-process usage
- [The Agent Loop](../architecture/the-agent-loop.md) — the five phases in detail
