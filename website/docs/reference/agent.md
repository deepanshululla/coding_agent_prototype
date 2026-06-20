---
sidebar_position: 1
title: "agent.py"
description: The core agent loop — streaming, tool dispatch, and iteration control.
---

# agent.py

`src/agent.py` is the heart of the system. It implements the nested outer/inner loop that drives the agent: streaming LLM responses, accumulating tool call fragments, executing tools in parallel, and feeding results back into the conversation. See [the agent loop](../architecture/the-agent-loop.md) for a narrative walkthrough of how these phases connect.

:::note
The signatures and behavior described here reflect the shipped `src/agent.py`.
:::

---

## Constants

### `MAX_ITERATIONS`

```python
MAX_ITERATIONS: int = 30
```

The maximum number of inner-loop iterations before the agent stops, regardless of pending tool calls. Prevents runaway loops caused by a model that keeps requesting tools without converging.

---

## Public API

### `run_agent`

```python
async def run_agent(task: str) -> list[dict]
```

Entry point for the agent. Accepts a plain-English task, initializes the conversation, and runs the outer/inner loop until the model signals it is done (or `MAX_ITERATIONS` is reached).

**Parameters**

| Parameter | Type  | Description                          |
|-----------|-------|--------------------------------------|
| `task`    | `str` | The user's task, passed as the first user message. |

**Returns** `list[dict]` — the final message history (all user, assistant, and tool messages). Streamed text and tool invocations are also printed to stdout as they arrive.

**Raises** Does not raise. Errors from the provider surface as Python exceptions that bubble up to `main.py`.

**Usage**

```python
import asyncio
from agent import run_agent

asyncio.run(run_agent("list all Python files in the project"))
```

---

## Internal helpers

These functions are module-private (prefixed with `_`). They are documented here because understanding them is necessary to understand the loop.

### `_execute_tools_parallel`

```python
async def _execute_tools_parallel(tool_calls: list[dict]) -> list[ToolResult]
```

Fans out a batch of tool calls to `asyncio.gather`, running all of them concurrently. Returns results in the same order as the input list.

**Parameters**

| Parameter    | Type         | Description                                                    |
|--------------|--------------|----------------------------------------------------------------|
| `tool_calls` | `list[dict]` | List of dicts with keys `id`, `name`, and `input` (parsed dict). |

**Returns** `list[ToolResult]` — one result per call, preserving order.

**Error behavior** Never raises. If a tool raises an exception, `_execute_one_tool` catches it and returns a `ToolResult` with `is_error=True`.

---

### `_execute_one_tool`

```python
async def _execute_one_tool(tool_call: dict) -> ToolResult
```

Resolves the tool name against `TOOL_REGISTRY`, invokes the async function with unpacked keyword arguments, and wraps the string output in a `ToolResult`.

**Parameters**

| Parameter   | Type   | Description                                         |
|-------------|--------|-----------------------------------------------------|
| `tool_call` | `dict` | Single dict with keys `id`, `name`, and `input`.   |

**Returns** `ToolResult` with `is_error=False` on success, `is_error=True` if the tool name is unknown or the function raises.

**Error behavior** Catches all exceptions; never re-raises. Unknown tool names produce `ToolResult(..., f"Unknown tool: {name}", is_error=True)`.

---

## The loop's phases

`run_agent` iterates through five phases on each inner-loop tick. The table below maps the phase labels used in the source to what happens in each.

| Phase | Label in source | What happens |
|-------|-----------------|--------------|
| A | Stream from LLM | Calls `stream_response(messages, system_prompt)`, accumulates text into `text_buf` and tool call fragments into `tool_acc` keyed by `index`. Prints text to stdout as it arrives. |
| B | Append assistant turn | Builds the assistant message dict (with `tool_calls` if any) and appends it to `messages`. |
| C | Stop check | If `finish_reason == "stop"` or no tool calls were requested, sets `has_more_tool_calls = False` and `continue`s. |
| D | Execute tools | Parses `arguments_buf` via `json.loads` (only here, after the stream ends), calls `_execute_tools_parallel`. |
| E | Push tool results | Appends one `{"role": "tool", "tool_call_id": ..., "content": ...}` message per result. |

The outer loop exists to support follow-up ("steering") messages queued while the agent is running. In v1, the outer loop always breaks after the inner loop finishes — no follow-up support yet.

```python
# Simplified skeleton
async def run_agent(task: str) -> list[dict]:
    system_prompt = build_system_prompt()
    messages = [{"role": "user", "content": task}]

    while True:                                    # outer loop
        has_more_tool_calls = True
        iteration = 0

        while (has_more_tool_calls or pending_messages) and iteration < MAX_ITERATIONS:
            iteration += 1

            # Phase A — stream
            text_buf, tool_acc, finish_reason = "", {}, None
            async for chunk in stream_response(messages, system_prompt):
                ...  # accumulate

            # Phase B — append assistant turn
            messages.append({"role": "assistant", "content": text_buf, "tool_calls": ...})

            # Phase C — stop?
            if finish_reason == "stop" or not tool_calls:
                has_more_tool_calls = False
                continue

            # Phase D — execute
            results = await _execute_tools_parallel(parsed_calls)

            # Phase E — push results
            for r in results:
                messages.append({"role": "tool", "tool_call_id": r.tool_call_id, "content": r.content})

        break  # no follow-up support in v1
```

:::warning Streaming gotcha
Tool call `arguments` arrive as partial JSON string fragments across multiple chunks. Buffer them in `tool_acc[index]["arguments_buf"]` and call `json.loads()` only once, after the stream ends. Parsing mid-stream will fail on incomplete JSON.
:::

---

## Related pages

- [The Agent Loop](../architecture/the-agent-loop.md) — narrative explanation of the loop's design
- [tools.py](./tools.md) — the 7 tool implementations and `TOOL_REGISTRY`
- [provider.py](./provider.md) — `stream_response` and chunk format
- [types_.py](./types.md) — `ToolResult` dataclass
- [Session Format](./session-format.md) — the `messages` list shape
