---
sidebar_position: 2
title: The Agent Loop
description: A step-by-step walkthrough of run_agent() — the outer/inner loop structure, Phases A–E of each iteration, MAX_ITERATIONS, and finish_reason handling.
---

# The Agent Loop

The agent loop in `src/agent.py` is the centerpiece of the entire system. Everything else — the provider, the tools, the prompt builder — exists to serve this loop. Understanding it means understanding how any coding agent works.

:::note
`src/agent.py` is implemented. The code on this page reflects the shipped implementation.
:::

## Structure at a glance

The loop is nested: an outer loop that handles follow-up messages wraps an inner loop that runs the actual tool-call cycle.

```
Outer loop  →  re-enters if follow-up messages are queued after the agent finishes
Inner loop  →  streams from the LLM, executes tools, pushes results, repeats
```

In v1, the outer loop exits immediately after the inner loop finishes (no steering/follow-up support yet). But the structure is there so adding mid-run input later requires only filling in one `break`.

## The full `run_agent()` function

```python
import asyncio
import json
from provider import stream_response
from prompts import build_system_prompt
from tools import TOOL_REGISTRY
from types_ import ToolResult

MAX_ITERATIONS = 30

async def run_agent(task: str) -> list[dict]:
    system_prompt = build_system_prompt()
    messages: list[dict] = [{"role": "user", "content": task}]
    pending_messages: list[dict] = []

    # OUTER LOOP: re-enter if follow-up messages arrive after agent finishes
    while True:
        has_more_tool_calls = True
        iteration = 0

        # INNER LOOP: tool-call cycle
        while (has_more_tool_calls or pending_messages) and iteration < MAX_ITERATIONS:
            iteration += 1

            if pending_messages:
                messages.extend(pending_messages)
                pending_messages.clear()

            # ── Phase A: Stream from LLM ──────────────────────────────────
            text_buf = ""
            # tool_acc: index → {id, name, arguments_buf}
            tool_acc: dict[int, dict] = {}
            finish_reason = None

            async for chunk in stream_response(messages, system_prompt):
                delta = chunk.choices[0].delta
                finish_reason = chunk.choices[0].finish_reason or finish_reason

                # Text fragment
                if delta.content:
                    text_buf += delta.content
                    print(delta.content, end="", flush=True)

                # Tool call fragments (may be multiple tool calls per turn)
                if delta.tool_calls:
                    for tc_chunk in delta.tool_calls:
                        idx = tc_chunk.index
                        if idx not in tool_acc:
                            tool_acc[idx] = {"id": "", "name": "", "arguments_buf": ""}
                        if tc_chunk.id:
                            tool_acc[idx]["id"] = tc_chunk.id
                        if tc_chunk.function and tc_chunk.function.name:
                            tool_acc[idx]["name"] = tc_chunk.function.name
                            print(f"\n▸ {tc_chunk.function.name}", end="", flush=True)
                        if tc_chunk.function and tc_chunk.function.arguments:
                            tool_acc[idx]["arguments_buf"] += tc_chunk.function.arguments

            print()  # newline after streamed text

            # Build finalized tool calls (parse JSON once, after stream ends)
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

            # ── Phase B: Append assistant turn to history ─────────────────
            assistant_msg: dict = {"role": "assistant", "content": text_buf or None}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            # ── Phase C: Stop check ───────────────────────────────────────
            if finish_reason == "stop" or not tool_calls:
                has_more_tool_calls = False
                continue

            # ── Phase D: Execute tool calls in parallel ───────────────────
            parsed_calls = [
                {"id": tc["id"], "name": tc["function"]["name"],
                 "input": json.loads(tc["function"]["arguments"])}
                for tc in tool_calls
            ]
            results = await _execute_tools_parallel(parsed_calls)

            # ── Phase E: Push tool results — one "tool" message per result ─
            for r in results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": r.tool_call_id,
                    "content": r.content,
                })

        break  # no follow-up support in v1
```

## Phase-by-phase breakdown

### Phase A — Stream from LLM

`stream_response()` yields OpenAI-format chunks. The loop processes two kinds of delta content simultaneously:

- **Text fragments** (`delta.content`): appended to `text_buf` and printed immediately to stdout. This is what gives the agent its "thinking out loud" feel.
- **Tool call fragments** (`delta.tool_calls`): accumulated by `index` into `tool_acc`. Each entry buffers the `id`, `name`, and partial `arguments_buf`.

The `finish_reason` field arrives on the final chunk. Keep the running value across chunks with `finish_reason = chunk.choices[0].finish_reason or finish_reason` — earlier chunks carry `None`.

After the stream ends, `tool_acc` is converted into finalized `tool_calls` dicts. Crucially, `json.loads()` is called here — **not** during streaming — because `arguments_buf` is only a complete JSON string once all fragments have arrived. See [Streaming & Event Accumulation](./streaming-and-events.md) for details.

### Phase B — Append assistant turn to history

Every assistant response goes into `messages` immediately after streaming finishes. The shape is:

```python
{
    "role": "assistant",
    "content": text_buf or None,   # None if the model only emitted tool calls
    "tool_calls": [...]            # present only when tool_calls is non-empty
}
```

This is critical for correctness: the LLM's next call must see the full history including the assistant's decision to invoke tools. Skipping this step causes the model to lose context.

### Phase C — Stop check

Two conditions terminate the inner loop's current iteration without proceeding to tool execution:

1. `finish_reason == "stop"` — the model finished with a plain text response.
2. `not tool_calls` — the model produced no tool call requests in this turn (even if `finish_reason` was `"tool_calls"`, which shouldn't happen, but is defensive).

When either condition is true, `has_more_tool_calls` is set to `False` and the inner loop condition (`has_more_tool_calls or pending_messages`) will fail on the next check, exiting the inner loop.

### Phase D — Execute tool calls in parallel

The model can request multiple tools in a single turn. They are all dispatched simultaneously:

```python
async def _execute_tools_parallel(tool_calls: list[dict]) -> list[ToolResult]:
    tasks = [_execute_one_tool(tc) for tc in tool_calls]
    return await asyncio.gather(*tasks)

async def _execute_one_tool(tool_call: dict) -> ToolResult:
    name = tool_call["name"]
    args = tool_call["input"]
    print(f"  [executing {name} {args}]")
    try:
        fn = TOOL_REGISTRY.get(name)
        if fn is None:
            return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
        result = await fn(**args)
        print(f"  [✓ {name}: {len(result)} chars]")
        return ToolResult(tool_call["id"], name, result)
    except Exception as e:
        return ToolResult(tool_call["id"], name, str(e), is_error=True)
```

`asyncio.gather` runs all `_execute_one_tool` coroutines concurrently. If the model asks to `read_file` and `list_dir` simultaneously, both calls are in flight at the same time. For blocking operations (subprocess, file I/O), tool implementations use `await asyncio.to_thread(fn, *args)` to avoid blocking the event loop.

Tool errors are **never raised**. Every failure returns a `ToolResult` with `is_error=True` and a descriptive error string. This lets the model read the error, reason about it, and try a different approach in the next iteration.

### Phase E — Push tool results

Each tool result becomes its own `role: "tool"` message in the conversation history:

```python
{
    "role": "tool",
    "tool_call_id": r.tool_call_id,
    "content": r.content,
}
```

One message per result, not batched. The `tool_call_id` ties the result back to the specific tool call in the preceding assistant message. After all results are pushed, the inner loop continues — the model will see its prior tool requests plus all their results and decide what to do next.

## The outer loop

The outer loop's purpose is to handle **steering messages** — follow-up inputs that arrive after the agent would otherwise stop. In v1, `pending_messages` is never populated externally, so the outer loop always breaks after one pass.

The structure is preserved because real agents need it: a user might queue a clarifying message while the agent is mid-run, and the outer loop re-enters the inner loop with that message prepended to history.

## MAX_ITERATIONS

`MAX_ITERATIONS = 30` is a safety limit. Without it, a model that keeps generating tool calls (either because the task is complex or because it's stuck in a bad pattern) would loop indefinitely.

When the limit is hit, the inner loop exits without any explicit error. In a production agent, you would surface this to the user. In v1, the process simply returns.

:::tip
30 iterations is generous for most coding tasks. A typical "add type hints to this file" task takes 3–6 iterations: explore → read → edit → verify → respond. Bump it higher only for tasks that genuinely require deep exploration.
:::

## Why outer vs inner?

The split mirrors pi.dev's design. The inner loop is the "thinking" cycle: ask → act → observe → repeat. The outer loop is the "conversation" cycle: finish a thought, wait for more input, think again.

Keeping them separate makes each concern clear. The inner loop never needs to know whether there will be a follow-up. The outer loop never needs to know about tool execution.

## Related pages

- [Streaming & Event Accumulation](./streaming-and-events.md) — what Phase A actually sees chunk by chunk
- [Message Types](./message-types.md) — the exact shapes appended in Phases B and E
- [The Provider Layer](./provider-layer.md) — what `stream_response()` does before chunks reach the loop
