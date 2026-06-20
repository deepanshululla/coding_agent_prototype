---
sidebar_position: 1
title: "Layer 10.1 — The `emit()` Seam"
description: Refactor every print() in agent.py into an emit(event) call dispatched to a renderer, shipping a StdoutRenderer that reproduces the original output exactly.
---

# Layer 10.1 — The `emit()` Seam

:::note Implemented
This step is implemented on branch `step/phase-10-1-event-seam` (plan: `plans/tutorial/phase-10-1-event-seam.md`).
:::

:::note Starting point
The finished stdout agent from Phase 9: `src/agent.py`, `src/tools.py`, `src/provider.py`, `src/prompts.py`, `src/types_.py`, `main.py`, and a passing test suite (`uv run pytest -q` → 17 passed). No UI yet — just the loop printing to stdout.
:::

Right now `agent.py` has five `print()` calls scattered through the loop. That's fine for a script, but it makes the output unconfigurable: there's no way to redirect tokens to a widget, add color, or swap in a full-screen UI without editing the loop itself.

This layer introduces a **single indirection** — an `emit(event)` function — between the loop and whatever consumes its output. The loop calls `emit`; the renderer decides what to do with each event. The loop never changes again.

The design is documented in [ADR-0009](../../architecture-decisions.md): the event seam is the one architectural boundary that makes every subsequent UI layer possible.

## What you'll learn

- Why an event seam is better than parameterising `print` calls.
- The five event types the agent emits (`text_delta`, `tool_call_start`, `tool_call_end`, `turn_end`, `agent_end`).
- How to write a `StdoutRenderer` that is byte-for-byte backward compatible with the original `print()` output.
- How to select a renderer at startup with `AGENT_UI` so the default is invisible to existing callers.

## Build it

### Step 1 — Create `src/renderer_stdout.py`

This is the **only** renderer you ship in this layer. Its job: reproduce the exact characters that the old `print()` calls produced. If you diff the output before and after, you should see nothing.

```python
# src/renderer_stdout.py

"""Default renderer: plain-text stdout.

Reproduces the original print() output exactly so AGENT_UI=stdout (the
default) is a no-op change from the caller's point of view.
"""


def emit(event: dict) -> None:
    t = event["type"]
    if t == "text_delta":
        print(event["delta"], end="", flush=True)
    elif t == "tool_call_start":
        print(f"\n▸ {event['name']}", end="", flush=True)
    elif t == "tool_call_end":
        status = "✓" if not event["is_error"] else "✗"
        print(f"  [{status} {event['name']}: {event['chars']} chars]")
    elif t == "turn_end":
        print()  # newline after the streamed turn
    # agent_end: no output in stdout mode
```

The `tool_call_end` event includes both the success/error flag and the char count. The original loop printed `[✓ name: N chars]` or `[executing name args]` in `_execute_one_tool`; the renderer reconstructs that from the event fields.

### Step 2 — Create `src/renderer.py` (the selector)

```python
# src/renderer.py

"""Selects the active renderer based on AGENT_UI and exposes emit().

Import this module; never import a renderer directly from agent code.
"""

import os

_UI = os.getenv("AGENT_UI", "stdout")

if _UI == "tui":
    from tui.emit import emit  # noqa: F401 — populated in Layer 10.2
else:
    from renderer_stdout import emit  # noqa: F401
```

At import time `renderer.py` reads `AGENT_UI` once and resolves the right `emit`. Callers do `from renderer import emit` and never think about which renderer is active.

### Step 3 — Refactor `src/agent.py`

Replace the five `print()` calls with `emit(event)` calls. The loop logic is **unchanged** — only the output lines move.

Add the import at the top of the file:

```python
from renderer import emit
```

Then swap each `print` for an `emit`:

```diff
         if getattr(delta, "content", None):
             text_buf += delta.content
-            print(delta.content, end="", flush=True)
+            emit({"type": "text_delta", "delta": delta.content})

         for tc_chunk in getattr(delta, "tool_calls", None) or []:
             idx = tc_chunk.index
             slot = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments_buf": ""})
             if tc_chunk.id:
                 slot["id"] = tc_chunk.id
             fn = getattr(tc_chunk, "function", None)
             if fn and fn.name:
                 slot["name"] = fn.name
-                print(f"\n▸ {fn.name}", end="", flush=True)
+                emit({"type": "tool_call_start", "index": idx,
+                      "tool_call_id": slot["id"], "name": fn.name})
             if fn and fn.arguments:
                 slot["arguments_buf"] += fn.arguments

-    print()  # newline after the streamed turn
+    emit({"type": "turn_end", "iteration": iteration,
+          "finish_reason": finish_reason or "stop",
+          "tool_calls_count": len(tool_calls)})
```

In `_execute_one_tool`, replace the two status prints:

```diff
     name = tool_call["name"]
     args = tool_call["input"]
-    print(f"  [executing {name} {args}]")
+    # tool_call_start was already emitted during streaming; no event here
     fn = TOOL_REGISTRY.get(name)
     if fn is None:
         return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
     try:
         result = await fn(**args)
     except Exception as e:
         return ToolResult(tool_call["id"], name, f"Error: {e}", is_error=True)
-    print(f"  [✓ {name}: {len(result)} chars]")
+    emit({"type": "tool_call_end", "index": tool_call.get("index", 0),
+          "tool_call_id": tool_call["id"], "name": name,
+          "content": result, "is_error": False, "chars": len(result)})
     return ToolResult(tool_call["id"], name, result)
```

And emit `agent_end` just before `return messages`:

```diff
+    emit({"type": "agent_end", "total_iterations": iteration, "status": "ok"})
     return messages
```

:::tip Pass the index through
`_execute_one_tool` needs `tool_call["index"]` to emit the right `tool_call_end`. Update `_execute_tools_parallel` to include `"index"` in each parsed call dict:

```python
parsed_calls = [
    {
        "id": tc["id"],
        "index": i,            # ← add this
        "name": tc["function"]["name"],
        "input": json.loads(tc["function"]["arguments"] or "{}"),
    }
    for i, tc in enumerate(tool_calls)
]
```
:::

:::warning Error path
The `is_error=True` branch in `_execute_one_tool` should also emit `tool_call_end`:

```python
if fn is None:
    emit({"type": "tool_call_end", "index": tool_call.get("index", 0),
          "tool_call_id": tool_call["id"], "name": name,
          "content": f"Unknown tool: {name}", "is_error": True, "chars": 0})
    return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
```

The original loop printed nothing on unknown-tool errors; the renderer's `tool_call_end` branch handles the display now.
:::

## Test it

### Behavior (BDD)

Verify this layer as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Scenario: StdoutRenderer output is identical to the original print() output
  Given the agent is run with AGENT_UI=stdout (the default)
  When the agent processes a task that produces streamed text and one tool call
  Then the captured stdout is byte-for-byte identical to the output produced
       by the same task before the emit() refactor
  And the final message history contains the same assistant and tool messages
```

Run this as an integration scenario with the [BDD framework](../../guides/bdd-integration-testing.md).

The scenario fails before the refactor because `renderer_stdout.py` does not exist and `from renderer import emit` raises `ImportError`. After the refactor it passes because the stdout renderer reconstructs the original lines from events.

### Existing test suite

The 17 tests from Phase 9 must still pass without change:

```bash
uv run pytest -q
# 17 passed
```

If any test monkeypatches `print` directly in `agent`, update it to capture `renderer.emit` calls instead — the events carry equivalent information.

## Run it

```bash
# Default: AGENT_UI=stdout — output is identical to before
uv run main.py "list the files in the current directory"

# Explicit: same thing
AGENT_UI=stdout uv run main.py "list the files in the current directory"
```

You should see the same streamed output you saw in Phase 8. The refactor is invisible to the user.

:::tip Architecture pattern
The `emit()` seam you build here is the first step toward an [event-sourced run log](../../architecture-patterns/event-sourcing.md) — every loop action becomes a typed event that renderers (and, later, audits and replays) consume.
:::

## Recap

The `emit()` seam is in place. `agent.py` no longer calls `print` directly; it dispatches typed events to whichever renderer `AGENT_UI` selects. The `StdoutRenderer` preserves the exact original output.

The next step is to build something that actually uses the seam: a minimal Textual app with a scrollable transcript pane.

→ [Layer 10.2 — The Transcript Pane](./2-transcript.md)
