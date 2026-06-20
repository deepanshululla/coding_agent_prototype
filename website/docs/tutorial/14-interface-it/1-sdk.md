---
sidebar_position: 1
title: "Layer 14.1 — The SDK"
description: Import run_agent() from agent.py and drive it from your own async code, iterating typed events instead of parsing stdout.
---

# Layer 14.1 — The SDK

:::note Starting point
The extended agent from Phase 13 with a TUI (Phase 10). `run_agent(task)` in `src/agent.py` returns the final message history (`list[dict]`). Entry is human/CLI only — `main.py` calls it; nothing else can.
:::

Every feature you've built so far — streaming, tools, the event seam, the TUI — is inside the process. To embed the agent in another program (a test harness, a CI bot, a web service), you need to call `run_agent` as a library function, not as a subprocess. The loop already returns the message history; the emit() seam already fires typed events. This layer wires those two facts together so a caller can observe both.

The design is documented in [Using the Agent as a Library](../../programmatic-usage/sdk.md). This page is the hands-on build step.

## What you'll learn

- How `run_agent` already exposes a clean Python API — the CLI is just a thin wrapper around it.
- How to collect typed events from the emit() seam in a caller-controlled queue instead of letting them go to a renderer.
- How to verify that the event sequence and the returned message history agree with what a stdout run would produce.
- The pattern for driving the agent from a test, a script, or another service.

## Build it

### Step 1 — Understand what you already have

`run_agent` is already a callable async function:

```python
# src/agent.py (existing)
async def run_agent(task: str) -> list[dict]:
    """Run the agent to completion on task. Returns the final message history."""
    ...
    return messages
```

And `src/renderer.py` already selects an emit function at import time based on `AGENT_UI`. That's the hook you'll use to redirect events to a caller-controlled collector instead of to the terminal.

### Step 2 — Create `src/sdk.py`

Add a thin wrapper that overrides the renderer for the duration of a single `run_agent` call, collecting all emitted events into a list:

```python
# src/sdk.py

"""SDK entry point: run_agent with typed-event collection.

Drives run_agent() while collecting every emitted event into a list,
so callers can iterate events and inspect the final message history
without parsing stdout.
"""

from __future__ import annotations

import asyncio
from typing import Any

import renderer as _renderer

from agent import run_agent


async def run_agent_collecting(
    task: str,
) -> tuple[list[dict[str, Any]], list[dict]]:
    """Run the agent and return (events, message_history).

    Events are collected in emit order. The message history is the same
    list that run_agent() returns — assistant turns, tool calls, tool results.
    """
    collected: list[dict[str, Any]] = []

    original_emit = _renderer.emit

    def collecting_emit(event: dict) -> None:
        collected.append(event)
        original_emit(event)   # still render to the active UI

    _renderer.emit = collecting_emit  # type: ignore[assignment]
    try:
        messages = await run_agent(task)
    finally:
        _renderer.emit = original_emit  # restore regardless of exception

    return collected, messages
```

:::note Why monkey-patch `renderer.emit`?
`renderer.emit` is a module-level name that `agent.py` imports with `from renderer import emit`. Replacing `_renderer.emit` directly patches the attribute on the module object, which is what the agent references at call time. This is the same pattern used in tests — lightweight, no framework needed, and easily restored in `finally`.

For a production SDK you would wire a proper callback into `run_agent` instead of patching. This layer shows the minimal seam; [Phase 15](../15-steering.md) shows how to add first-class callback support.
:::

### Step 3 — Understand the event types

Your caller will see these event types in order, sourced from the emit() seam added in Phase 10:

| Type | When fired | Key fields |
|------|-----------|------------|
| `text_delta` | Each streamed text fragment | `delta` |
| `tool_call_start` | When a tool name first arrives in the stream | `index`, `tool_call_id`, `name` |
| `tool_call_end` | After `_execute_one_tool` returns | `index`, `tool_call_id`, `name`, `content`, `is_error`, `chars` |
| `turn_end` | End of each inner-loop iteration | `iteration`, `finish_reason`, `tool_calls_count` |
| `agent_end` | When the outer loop exits | `total_iterations`, `status` |

The event schema is defined in full in [Using the Agent as a Library](../../programmatic-usage/sdk.md) and [JSON Event Stream Mode](../../programmatic-usage/json-event-stream.md).

### Step 4 — Drive the agent from a script

```python
# my_script.py  (run from repo root)
import asyncio
import sys

sys.path.insert(0, "src")

from dotenv import load_dotenv
from sdk import run_agent_collecting


async def main() -> None:
    load_dotenv()
    events, messages = await run_agent_collecting(
        "List all Python files in src/ and count lines in each."
    )

    print("\n--- event summary ---")
    for e in events:
        t = e["type"]
        if t == "text_delta":
            pass  # already rendered to the TUI/stdout
        elif t == "tool_call_start":
            print(f"  tool started: {e['name']}")
        elif t == "tool_call_end":
            status = "ok" if not e["is_error"] else "ERROR"
            print(f"  tool done:    {e['name']} [{status}] {e['chars']} chars")
        elif t == "agent_end":
            print(f"  agent done in {e['total_iterations']} iterations, status={e['status']}")

    print(f"\n--- message history: {len(messages)} messages ---")
    for m in messages:
        role = m.get("role", "?")
        if role == "assistant":
            n_tools = len(m.get("tool_calls") or [])
            print(f"  assistant: {len(m.get('content') or '')} text chars, {n_tools} tool calls")
        elif role == "tool":
            print(f"  tool result: {m['tool_call_id'][:12]}…")
        else:
            print(f"  {role}: {str(m.get('content', ''))[:60]}")


asyncio.run(main())
```

Run it:

```bash
uv run my_script.py
```

## Test it

### Behavior (BDD)

Verify this layer as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Scenario: SDK caller receives typed events in order with matching message history
  Given the agent is called via run_agent_collecting() with a simple task
  When the agent completes (no real API call — stream_response is mocked)
  Then the events list contains at least one text_delta event
  And the events list contains a tool_call_start followed by a tool_call_end
       for each tool call, in that order
  And the final event has type "agent_end" with status "ok"
  And the returned message history contains the same assistant turns and
       tool results that a direct run_agent() call would return
```

Run this as an integration scenario with the [BDD framework](../../guides/bdd-integration-testing.md).

The scenario fails before `src/sdk.py` exists because `run_agent_collecting` is not importable. After the build it passes because the collecting emit wrapper captures events in order while `run_agent` returns the same history it always did.

### Unit test

Add a test in `tests/test_sdk.py` using the existing mock pattern from Phase 9:

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import sys
sys.path.insert(0, "src")

from sdk import run_agent_collecting


def make_stop_chunk(text: str = "done"):
    """Build a minimal mock chunk that ends the stream."""
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta.content = text
    chunk.choices[0].delta.tool_calls = None
    chunk.choices[0].finish_reason = "stop"
    return chunk


async def fake_stream(*args, **kwargs):
    yield make_stop_chunk("Hello from mock.")


@pytest.mark.asyncio
@patch("agent.stream_response", side_effect=fake_stream)
async def test_sdk_collects_events_and_returns_history(mock_stream):
    events, messages = await run_agent_collecting("ping")

    text_events = [e for e in events if e["type"] == "text_delta"]
    assert text_events, "expected at least one text_delta event"
    assert any(e["type"] == "agent_end" for e in events)
    assert events[-1]["type"] == "agent_end"

    assert messages[0] == {"role": "user", "content": "ping"}
    assert any(m["role"] == "assistant" for m in messages)
```

Run the tests:

```bash
uv run pytest tests/test_sdk.py -v
```

## Run it

```bash
# Drive the agent as a library, collecting events
uv run my_script.py

# Or from inside an async REPL / notebook
python - <<'EOF'
import asyncio, sys
sys.path.insert(0, "src")
from dotenv import load_dotenv
from sdk import run_agent_collecting

load_dotenv()
events, messages = asyncio.run(
    run_agent_collecting("What is 2 + 2?")
)
print(f"Got {len(events)} events, {len(messages)} messages")
EOF
```

## Recap

`run_agent` was always a callable library function — this layer makes that explicit. `sdk.py` adds a collecting wrapper that taps the emit() seam to return typed events alongside the message history, giving programmatic callers structured access to everything the agent does.

The next step is to expose that same interface across a process boundary using a JSON-RPC protocol, so callers in any language can drive the agent over stdin/stdout or HTTP.

→ [Layer 14.2 — RPC Mode](./2-rpc-mode.md)
