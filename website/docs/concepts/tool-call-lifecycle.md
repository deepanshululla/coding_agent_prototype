---
sidebar_position: 4
title: Tool-Call Lifecycle
description: A step-by-step trace of one tool call from the model's request to the result appended in message history, covering streaming accumulation, JSON parsing, execution, and the next loop iteration.
---

# Tool-Call Lifecycle

When the model decides to use a tool, several things happen in sequence before the loop can continue. This page traces one complete cycle — from the first streaming chunk that carries a tool name to the moment the result is back in `messages` and the next iteration begins.

:::note
`src/agent.py` is implemented. The walkthrough below reflects the shipped implementation.
:::

## Overview

```
Stream chunks arrive
    → accumulate by index
    → finish_reason = "tool_calls"
    → json.loads arguments
    → append assistant turn to messages
    → execute tools in parallel
    → wrap each result as ToolResult
    → append role:"tool" messages
    → next loop iteration
```

## Step 1 — Stream fragments accumulate by index

The model does not send a tool call as a single message. It streams it as a sequence of delta chunks, each carrying a fragment. LiteLLM normalizes these to OpenAI's chunk format:

```python
chunk.choices[0].delta.tool_calls       # list of ToolCallChunk | None
  .index                                # which tool call (0, 1, 2...)
  .id                                   # tool call ID — only on first chunk for that index
  .function.name                        # tool name — only on first chunk
  .function.arguments                   # partial JSON string fragment
```

The agent buffers fragments into a dict keyed by `index`:

```python
tool_acc: dict[int, dict] = {}   # index → {id, name, arguments_buf}

if delta.tool_calls:
    for tc_chunk in delta.tool_calls:
        idx = tc_chunk.index
        if idx not in tool_acc:
            tool_acc[idx] = {"id": "", "name": "", "arguments_buf": ""}
        if tc_chunk.id:
            tool_acc[idx]["id"] = tc_chunk.id
        if tc_chunk.function and tc_chunk.function.name:
            tool_acc[idx]["name"] = tc_chunk.function.name
        if tc_chunk.function and tc_chunk.function.arguments:
            tool_acc[idx]["arguments_buf"] += tc_chunk.function.arguments
```

Key details:
- `id` and `name` appear **only on the first chunk** for each index. Later chunks have `None` for both — the `if tc_chunk.id` guard prevents overwriting a real value with `None`.
- `arguments` arrives as a **partial JSON string** across multiple chunks. The `+=` concatenation builds the complete string.
- If the model requests two tools simultaneously, you get interleaved chunks with `index=0` and `index=1`. The dict handles this correctly.

:::warning
Never call `json.loads` on a partial `arguments_buf` mid-stream. The string is incomplete until `finish_reason` is set. Parsing early will raise a `JSONDecodeError`.
:::

## Step 2 — finish_reason signals end of stream

While looping over chunks, the agent tracks the finish reason:

```python
finish_reason = chunk.choices[0].finish_reason or finish_reason
```

LiteLLM uses OpenAI's vocabulary. When the model requests tools, the stream ends with:

```
finish_reason = "tool_calls"
```

(Not `"tool_use"` — that is Anthropic's raw format. LiteLLM normalizes it.)

When `finish_reason = "stop"`, the model is done and expects no more tool results. When it is `None`, the stream is still going.

## Step 3 — Finalize tool calls: json.loads after stream ends

Once the `async for` loop over chunks exits, all fragments are complete. Now it is safe to parse:

```python
tool_calls = [
    {
        "id": tc["id"],
        "type": "function",
        "function": {
            "name": tc["name"],
            "arguments": tc["arguments_buf"],  # keep as string for message history
        },
    }
    for tc in tool_acc.values()
]
```

The `arguments` field stays as a JSON **string** in the tool_calls list. This is intentional: the OpenAI message format requires the string form. The dict form is only used internally during execution (Step 5).

## Step 4 — Append the assistant turn to messages

Before executing anything, the assistant's response is committed to history:

```python
assistant_msg: dict = {"role": "assistant", "content": text_buf or None}
if tool_calls:
    assistant_msg["tool_calls"] = tool_calls
messages.append(assistant_msg)
```

This happens before execution so that if a tool crashes mid-batch, the history still records what the model requested. The `content` field is `None` when the model sent only tool calls with no accompanying text, which is valid in the OpenAI format.

## Step 5 — Execute tools in parallel

The agent parses arguments now (safe to do because the stream is complete) and dispatches:

```python
parsed_calls = [
    {
        "id": tc["id"],
        "name": tc["function"]["name"],
        "input": json.loads(tc["function"]["arguments"])  # ← parse here, not mid-stream
    }
    for tc in tool_calls
]
results = await _execute_tools_parallel(parsed_calls)
```

`_execute_tools_parallel` uses `asyncio.gather` to run all tool coroutines concurrently. See [Async & Concurrency](./async-and-concurrency.md) for the details. Each tool is looked up by name in `TOOL_REGISTRY`:

```python
fn = TOOL_REGISTRY.get(name)
if fn is None:
    return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
result = await fn(**args)
return ToolResult(tool_call["id"], name, result)
```

Errors are **never raised** — they are returned as `ToolResult` with `is_error=True`. This lets the model see the error text and reason about what went wrong.

## Step 6 — Append tool result messages

Each `ToolResult` becomes its own `role: "tool"` message:

```python
for r in results:
    messages.append({
        "role": "tool",
        "tool_call_id": r.tool_call_id,
        "content": r.content,
    })
```

The `tool_call_id` links each result back to the specific tool call that produced it. When the model requested two tools, you get two separate tool messages, each with its own `tool_call_id`. The model sees them as paired responses.

:::info
In the OpenAI format, tool results are their own top-level messages with `role: "tool"`, not nested inside a `role: "user"` message. LiteLLM normalizes incoming chunks to this format and expects outgoing history in this format too.
:::

## Step 7 — Next loop iteration

With the tool results in `messages`, the inner loop cycles back. On the next iteration, `stream_response` sends the updated `messages` list (including the new tool results) and the model sees the outcome of its tool calls. It can then:

- Make more tool calls (inner loop continues)
- Produce a final text response (`finish_reason = "stop"` → `has_more_tool_calls = False`)

## Complete sequence diagram

```
Agent loop                    LiteLLM / Model              Tool functions
     │                              │                            │
     │── await stream_response ────▶│                            │
     │                              │── stream chunks ──────────▶│
     │◀─ chunk (index=0, name) ─────│                            │
     │◀─ chunk (index=0, args_frag) │                            │
     │◀─ chunk (finish="tool_calls")│                            │
     │                              │                            │
     │── json.loads args ───────────│                            │
     │── append assistant msg ──────│                            │
     │── asyncio.gather ────────────│──────────────────────────▶│
     │                              │                  (parallel)│
     │◀─ ToolResult ────────────────│◀──────────────────────────│
     │── append role:"tool" msgs ───│                            │
     │                              │                            │
     │── await stream_response ────▶│  (next iteration)         │
     │           ...                │                            │
```

## Related pages

- [Streaming & Events](../architecture/streaming-and-events.md) — deeper look at chunk structure and the streaming loop
- [Parallel Execution](../tools/parallel-execution.md) — how `asyncio.gather` runs tool batches
- [Async & Concurrency](./async-and-concurrency.md) — the event loop mental model
