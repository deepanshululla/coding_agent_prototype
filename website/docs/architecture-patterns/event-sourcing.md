---
sidebar_position: 8
title: Event Sourcing / Run Log
description: An append-only record of every decision and tool result — how the project's messages list is already a primitive event log, and how to generalize it to a typed RunLog that powers debugging, evals, and replay.
---

# Event Sourcing / Run Log

Every time the agent makes a decision, calls a tool, or receives a result, something happened.
An event log captures each of those moments as an immutable, typed record. Nothing is ever
overwritten. The full history of a run can be replayed to reconstruct state, drive evals, or
diagnose what went wrong.

:::note Design guidance, not v1
The shipped core is simpler than what this page describes. The `messages` list already acts as a
primitive event log (see [In this project](#in-this-project) below). The typed `RunLog`
and `emit()` seam are an architectural extension you can add without touching the core loop.
Adopt them when debugging complexity or an eval harness demands it.
:::

## The problem

A coding agent runs for minutes, issues dozens of tool calls, and produces diffs across multiple
files. When a run goes wrong — the wrong file got patched, a test started failing, the agent
looped — you need answers:

- Exactly what command ran at step 14?
- What was the model's reasoning before it issued that `write_file`?
- Did the test fail before or after the second patch?

Without a structured log, you're left digging through interleaved stdout lines. With one, you
replay the run, inspect any step, and feed it to an eval harness.

## The pattern

**Event sourcing** stores state as a sequence of events rather than as a mutable snapshot. Each
event is:

- **Immutable** — never updated in place, only appended.
- **Typed** — a defined structure with a timestamp, event kind, and payload.
- **Complete** — the full state of the system at any point can be derived by replaying events
  up to that point.

```
        agent loop
             │
   ┌─────────▼──────────┐   emit()    ┌──────────────────────┐
   │  Phase A: stream   │────────────▶│                      │
   │  Phase B: append   │────────────▶│   RunLog             │
   │  Phase D: execute  │────────────▶│   (append-only)      │
   │  Phase E: results  │────────────▶│                      │
   └────────────────────┘             └──────────┬───────────┘
                                                 │
                                    ┌────────────▼──────────┐
                                    │  consumers            │
                                    │  • debug viewer       │
                                    │  • eval harness       │
                                    │  • JSON event stream  │
                                    │  • replay engine      │
                                    └───────────────────────┘
```

A small set of event kinds covers the full lifecycle of a coding task:

| Event kind | When it fires |
|---|---|
| `TaskStarted` | `run_agent` is called with a task string |
| `ModelStreaming` | Phase A begins — the model starts generating |
| `ToolCallRequested` | The model requested a tool call (name + args) |
| `CommandRun` | A `bash` tool was dispatched (command string) |
| `FileRead` | A `read_file` call completed |
| `PatchApplied` | A `write_file` or `edit_file` succeeded |
| `ToolResult` | Any tool returned (with `is_error` flag) |
| `TestFailed` | A `bash pytest` returned non-zero exit |
| `PatchRevised` | The model issued a second `edit_file` for the same path |
| `TaskCompleted` | The outer loop exited cleanly |
| `TaskAborted` | `MAX_ITERATIONS` was hit or an unrecoverable error occurred |

## In this project

The `messages` list in `src/agent.py` is already a primitive event log. It is append-only — the
loop never mutates an existing entry, only appends:

```python
# src/agent.py — the messages list accumulates every turn
messages: list[dict] = [{"role": "user", "content": task}]

# Phase B — assistant turn appended
messages.append({"role": "assistant", "content": text_buf or None, "tool_calls": tool_calls})

# Phase E — one "tool" message per result, also appended
for r in results:
    messages.append({"role": "tool", "tool_call_id": r.tool_call_id, "content": r.content})
```

The structure is dictated by the OpenAI message format (for re-sending to the model), which
limits what it can carry cleanly: timestamps, event kinds, intermediate state, and metadata
outside the message content don't have a natural home.

**Generalizing to a typed `RunLog`** adds an independent stream of structured events that runs
alongside `messages`. The `emit()` function is the seam — it is already the mechanism used by
the [JSON event stream](../programmatic-usage/json-event-stream.md) and
[logging](../operations/logging.md):

```python
# src/types_.py (planned extension)
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

EventKind = Literal[
    "TaskStarted", "ModelStreaming", "ToolCallRequested",
    "CommandRun", "FileRead", "PatchApplied", "ToolResult",
    "TestFailed", "PatchRevised", "TaskCompleted", "TaskAborted",
]

@dataclass
class RunEvent:
    kind: EventKind
    payload: dict[str, Any] = field(default_factory=dict)
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

@dataclass
class RunLog:
    events: list[RunEvent] = field(default_factory=list)

    def emit(self, kind: EventKind, **payload: Any) -> None:
        self.events.append(RunEvent(kind=kind, payload=payload))
```

The log threads through the agent loop and each `_execute_one_tool` call emits at the right
phase:

```python
# src/agent.py (planned extension — emit() calls added at each loop phase)
async def run_agent(task: str, log: RunLog | None = None) -> list[dict]:
    log = log or RunLog()
    log.emit("TaskStarted", task=task)
    messages: list[dict] = [{"role": "user", "content": task}]

    while True:
        while has_more_tool_calls and iteration < MAX_ITERATIONS:
            iteration += 1

            # Phase A
            log.emit("ModelStreaming", iteration=iteration)
            async for chunk in stream_response(messages, system_prompt):
                ...

            # Phase B — assistant turn already goes into messages
            messages.append(assistant_msg)

            if not tool_calls:
                has_more_tool_calls = False
                continue

            # Phase D — emit before dispatch
            for tc in parsed_calls:
                log.emit("ToolCallRequested", name=tc["name"], args=tc["input"])

            results = await _execute_tools_parallel(parsed_calls, log=log)

            # Phase E — results go into messages and into the log
            for r in results:
                messages.append({"role": "tool", "tool_call_id": r.tool_call_id, "content": r.content})

        break

    log.emit("TaskCompleted", iterations=iteration)
    return messages


async def _execute_one_tool(tool_call: dict, log: RunLog) -> ToolResult:
    name = tool_call["name"]
    args = tool_call["input"]

    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        result = ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
        log.emit("ToolResult", name=name, is_error=True, content=result.content)
        return result

    result_str = await fn(**args)

    # Emit the specific event kind for dangerous / interesting tools
    if name == "bash":
        kind = "TestFailed" if "(exit code " in result_str and "1)" in result_str else "CommandRun"
        log.emit(kind, command=args.get("command"), output=result_str[:500])
    elif name in {"write_file", "edit_file"}:
        log.emit("PatchApplied", path=args.get("path"), tool=name)
    elif name == "read_file":
        log.emit("FileRead", path=args.get("path"))

    result = ToolResult(tool_call["id"], name, result_str)
    log.emit("ToolResult", name=name, is_error=result.is_error, chars=len(result_str))
    return result
```

### Replay: re-deriving state from the event stream

Because the log is append-only, you can reconstruct what happened at any iteration by filtering
events by iteration number:

```python
def replay_iteration(log: RunLog, iteration: int) -> dict:
    """Re-derive the state at a given iteration from the event log."""
    events = [e for e in log.events if e.payload.get("iteration") == iteration]
    patches = [e for e in log.events if e.kind == "PatchApplied" and
               log.events.index(e) <= next(
                   (i for i, ev in enumerate(log.events) if ev.payload.get("iteration", 0) > iteration),
                   len(log.events)
               )]
    return {
        "iteration": iteration,
        "tool_calls": [e.payload for e in events if e.kind == "ToolCallRequested"],
        "patches_so_far": [e.payload for e in patches],
    }
```

### Powering evals

A `RunLog` is the foundation of an eval harness. Given a task with a known-good outcome, run the
agent, capture the log, then assert over event sequences:

```python
async def test_agent_applies_patch_before_running_tests():
    log = RunLog()
    await run_agent("Fix the off-by-one error in utils.py", log=log)

    kinds = [e.kind for e in log.events]
    patch_idx = kinds.index("PatchApplied")
    test_idx = next(i for i, k in enumerate(kinds) if k == "CommandRun" and
                    "pytest" in log.events[i].payload.get("command", ""))

    assert patch_idx < test_idx, "agent must patch before running tests"
    assert "TestFailed" not in kinds[test_idx:], "tests should pass after the patch"
```

This is significantly more reliable than asserting over raw stdout lines or the final
`messages` list, because each assertion targets a named event with typed payload fields.

## Trade-offs

| | Benefit | Cost |
|---|---|---|
| **Typed events** | Evals, replay, and tooling can rely on stable field names | You maintain an event schema; adding a new tool kind means a new event |
| **Parallel emit** | `asyncio.gather` runs tools concurrently; events from different tools may interleave | Add a sequence number or per-tool `tool_call_id` to correlate events across parallel calls |
| **In-memory log** | Simple and fast | Lost on crash; for durability, flush to JSONL after each emit |
| **Separate from messages** | The log can carry metadata (timestamps, durations) that the OpenAI message format can't | Two places to look; keep them consistent by emitting from the same code path that appends to `messages` |
| **Replay fidelity** | The event log captures what happened | Replay re-runs the agent, it does not re-execute tools — true replay requires mocking tools with logged inputs/outputs |

:::tip Flush to JSONL for durability
Add a one-line flush to `emit()`:

```python
def emit(self, kind: EventKind, **payload: Any) -> None:
    event = RunEvent(kind=kind, payload=payload)
    self.events.append(event)
    if self._jsonl_path:
        with open(self._jsonl_path, "a") as f:
            f.write(json.dumps({"kind": kind, "ts": event.ts.isoformat(), **payload}) + "\n")
```

Now the log survives crashes and you can inspect it with `jq` while the agent is still
running.
:::

## Related

- [Command Pattern](./command-pattern.md) — making each tool call a first-class object; the `Command` object is what you emit into the log
- [Logging](../operations/logging.md) — the operational logging layer; the `emit()` seam is shared
- [JSON Event Stream](../programmatic-usage/json-event-stream.md) — the programmatic interface that consumes the same event stream
- [Sessions](../concepts/sessions.md) — how a session is structured; the `messages` list is the session's conversation record
- [Session Format](../reference/session-format.md) — the serialized form of `messages`; the `RunLog` is a richer companion record
