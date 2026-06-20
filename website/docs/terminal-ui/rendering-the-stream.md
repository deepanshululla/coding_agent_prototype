---
sidebar_position: 2
title: Rendering the Stream
description: How to turn streamed text deltas and tool-call markers from run_agent into live terminal UI updates using prompt_toolkit or Textual on a shared asyncio loop.
---

# Rendering the Stream

`run_agent` streams in real time: text fragments arrive from the model character-by-character; tool call names appear mid-stream; tool results arrive asynchronously after execution. The TUI's job is to route each of these events to the right widget as they happen.

:::note
This page describes the **planned TUI architecture**. v1 prints plain text to stdout. The `emit()` refactor shown below is the code change needed to unlock the TUI front-end.
:::

## The `emit()` refactor

Every observable event in `run_agent` currently maps to a `print()` call. The refactor replaces each one with `emit(event_dict)` — an indirection that lets you swap the renderer without touching the agent logic.

Here is the diff for `src/agent.py`:

```diff
+from renderer import emit   # selected at startup based on AGENT_UI

 async def run_agent(task: str) -> list[dict]:
     ...
     async for chunk in stream_response(messages, system_prompt):
         ...
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

Inside `_execute_one_tool`, replace the two status prints:

```diff
-    print(f"  [executing {name} {args}]")
+    # (no event at call-start; tool_call_start was already emitted during streaming)
     result = await fn(**args)
-    print(f"  [✓ {name}: {len(result)} chars]")
+    emit({"type": "tool_call_end", "index": ..., "tool_call_id": tool_call["id"],
+          "name": name, "content": result, "is_error": False,
+          "chars": len(result)})
```

And emit `agent_end` when the outer loop exits:

```diff
-    return messages
+    emit({"type": "agent_end", "total_iterations": iteration, "status": "ok"})
+    return messages
```

The full event schema is defined in [JSON Event Stream](../programmatic-usage/json-event-stream.md).

## The stdout renderer

The stdout renderer reconstructs v1 output from events, so `AGENT_UI=stdout` (the default) is backward-compatible:

```python
# src/renderer_stdout.py

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

## The TUI renderer

When `AGENT_UI=tui`, `emit` is a function that posts events to the running TUI application. Because `run_agent` is a coroutine running on the same asyncio event loop as the TUI, delivery is immediate — no threads, no queues.

### Shared event loop

The TUI drives the event loop. `run_agent` runs as a Task inside it:

```python
# src/tui/__init__.py  (sketch)

import asyncio
from tui.app import AgentApp

def run(task: str) -> None:
    app = AgentApp(task)
    asyncio.run(app.run_async())
```

```python
# src/tui/app.py  (sketch — Textual style)

from textual.app import App
from agent import run_agent

class AgentApp(App):
    def __init__(self, task: str) -> None:
        super().__init__()
        self.task = task

    async def on_mount(self) -> None:
        # Schedule run_agent as a background task on this event loop.
        asyncio.create_task(run_agent(self.task))
```

With prompt_toolkit the pattern is the same: `Application.run_async()` owns the loop; `run_agent` is a Task created inside `on_start` or an `asyncio.ensure_future` call.

### The TUI `emit`

```python
# src/tui/emit.py

from __future__ import annotations
_app: "AgentApp | None" = None

def set_app(app: "AgentApp") -> None:
    global _app
    _app = app

def emit(event: dict) -> None:
    if _app is None:
        return
    _app.handle_agent_event(event)
```

`handle_agent_event` dispatches to the appropriate widget:

```python
# inside AgentApp

def handle_agent_event(self, event: dict) -> None:
    t = event["type"]
    if t == "text_delta":
        self.query_one(TranscriptPane).append_text(event["delta"])
    elif t == "tool_call_start":
        self.query_one(ToolPanel).add_row(event["index"], event["name"])
    elif t == "tool_call_end":
        self.query_one(ToolPanel).finish_row(
            event["index"], ok=not event["is_error"], chars=event["chars"]
        )
    elif t == "turn_end":
        self.query_one(StatusBar).set_iteration(event["iteration"])
    elif t == "agent_end":
        self.query_one(StatusBar).set_done(event["total_iterations"])
```

## Event → widget mapping

| Event | Widget | Action |
|---|---|---|
| `text_delta` | `TranscriptPane` | Append `delta` to the end of the transcript buffer |
| `tool_call_start` | `ToolPanel` | Add a new row with the tool name and a spinner |
| `tool_call_end` | `ToolPanel` | Replace spinner with ✓ (or ✗), show char count |
| `turn_end` | `StatusBar` | Advance the iteration counter |
| `agent_end` | `StatusBar` | Show "done" state; unlock input box |

## Partial-JSON args

Tool-call arguments arrive as partial JSON strings spread across stream chunks. The agent buffers them in `tool_acc[idx]["arguments_buf"]` and only calls `json.loads` **after** the stream ends (in Phase D). The TUI follows the same rule: it does not attempt to preview argument values during streaming. The tool panel shows only the tool name while the stream is active; a short args preview (e.g., the first 60 chars of the parsed JSON) is appended to the row when `tool_call_end` arrives.

:::tip
If you want a live argument preview, you could speculatively render `arguments_buf` as raw text. Be careful: the string is not yet valid JSON during streaming, so don't try to `json.loads` it until `tool_call_end`.
:::

## Related pages

- [Overview](./overview.md) — the emit seam and AGENT_UI selection
- [Components](./components.md) — detailed widget specs
- [JSON Event Stream](../programmatic-usage/json-event-stream.md) — full event schema reference
