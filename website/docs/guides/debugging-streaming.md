---
sidebar_position: 3
title: Debugging Streaming
description: How to inspect raw LiteLLM chunks, the most common streaming bugs, and a symptom-to-cause reference table.
---

# Debugging Streaming

Streaming is the most error-prone part of building this agent. The LLM response arrives as a sequence of delta chunks, and several easy mistakes produce bugs that are silent until the agent executes the wrong tool, crashes on a `json.loads`, or hangs silently.

This page covers the two most useful debugging techniques and a reference table of the bugs you are most likely to encounter.

:::note
`src/provider.py` and `src/agent.py` are implemented. The patterns below reflect the shipped code and apply directly to the real files.
:::

---

## Print raw chunks to learn the shape

Before writing any accumulation logic, add a raw-print loop to understand what LiteLLM actually yields. Insert this in `src/provider.py` or in a throw-away script:

```python
import asyncio
import litellm

async def inspect_chunks():
    response = await litellm.acompletion(
        model="claude-sonnet-4-5",
        messages=[{"role": "user", "content": "What is 2+2? Also call list_dir on '.'"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "list_dir",
                    "description": "List a directory",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
            }
        ],
        stream=True,
    )
    async for i, chunk in enumerate(response):
        print(f"--- chunk {i} ---")
        delta = chunk.choices[0].delta
        print(f"  content:      {repr(delta.content)}")
        print(f"  tool_calls:   {delta.tool_calls}")
        print(f"  finish_reason:{chunk.choices[0].finish_reason}")

asyncio.run(inspect_chunks())
```

Run this with a model that will produce a tool call. You will see:

1. Early chunks deliver `content` fragments with `tool_calls=None`.
2. Tool-call chunks arrive with `tool_calls` set and `content=None`.
3. The first chunk for a given tool call index has `id` and `name` set; later chunks for the same index have `id=None` and `name=None` but carry more `arguments` JSON.
4. The final chunk has `finish_reason="tool_calls"` (not `"stop"`).

Seeing this once makes the accumulation logic obvious.

### Printing the accumulated state

Add a print after the stream loop to confirm your buffer looks correct before you call `json.loads`:

```python
async for chunk in stream_response(messages, system_prompt):
    # ... accumulation logic ...
    pass

# After the stream:
print("--- accumulated tool_acc ---")
for idx, tc in tool_acc.items():
    print(f"  [{idx}] id={tc['id']} name={tc['name']} args={tc['arguments_buf']!r}")
```

If `arguments_buf` is empty or truncated, the accumulation has a bug. If `name` is empty, the `if tc_chunk.function and tc_chunk.function.name` guard is missing.

---

## Common bugs

### 1. Parsing arguments mid-stream

The most common mistake: calling `json.loads` on a partial chunk.

```python
# WRONG — arguments_buf is incomplete on most chunks
if tc_chunk.function and tc_chunk.function.arguments:
    args = json.loads(tc_chunk.function.arguments)  # SyntaxError or partial dict

# CORRECT — accumulate, parse once after stream ends
tool_acc[idx]["arguments_buf"] += tc_chunk.function.arguments or ""
# ... after async for loop exits:
args = json.loads(tool_acc[idx]["arguments_buf"])
```

The symptom is a `JSONDecodeError` with a message like `Expecting value: line 1 column 5 (char 4)`, or — worse — silently truncated arguments that cause the tool to receive `None` for required parameters.

### 2. Overwriting `id` or `name` with `None` on later chunks

LiteLLM sets `id` and `name` only on the **first** chunk for a given tool-call index. Later chunks for the same index carry `id=None` and `name=None`. If you unconditionally overwrite:

```python
# WRONG — later chunks blank out the id and name
tool_acc[idx]["id"] = tc_chunk.id        # becomes None
tool_acc[idx]["name"] = tc_chunk.function.name  # becomes None
```

The fix is to check before overwriting:

```python
# CORRECT
if tc_chunk.id:
    tool_acc[idx]["id"] = tc_chunk.id
if tc_chunk.function and tc_chunk.function.name:
    tool_acc[idx]["name"] = tc_chunk.function.name
```

The symptom is an `id` of `None` in the assembled tool call, which causes the `role: "tool"` response message to have `"tool_call_id": None`, and the model usually errors or ignores the result.

### 3. Accumulating tool calls sequentially instead of by index

When the model calls multiple tools in one turn, each tool-call stream is interleaved. If you append to a list instead of keying by `index`, you conflate fragments from different tools.

```python
# WRONG — mixes fragments from different tools
tool_calls_list = []
if delta.tool_calls:
    for tc_chunk in delta.tool_calls:
        tool_calls_list.append(tc_chunk)  # index info lost

# CORRECT — key by index
tool_acc: dict[int, dict] = {}
if delta.tool_calls:
    for tc_chunk in delta.tool_calls:
        idx = tc_chunk.index
        if idx not in tool_acc:
            tool_acc[idx] = {"id": "", "name": "", "arguments_buf": ""}
        # update in place
```

The symptom is garbled argument JSON (fragments from tool A appended to tool B's buffer) or missing tools (only the last-seen index survives).

### 4. Expecting `"tool_use"` instead of `"tool_calls"` as the finish reason

If you have worked with the Anthropic SDK directly (not through LiteLLM), you may be used to `stop_reason: "tool_use"`. LiteLLM normalizes to OpenAI's vocabulary: the finish reason is `"tool_calls"`.

```python
# WRONG — this check never triggers through LiteLLM
if finish_reason == "tool_use":
    ...

# CORRECT
if finish_reason == "tool_calls":
    ...
```

The symptom is the agent always treating tool-call turns as `"stop"` — it appends the assistant message but never dispatches to `TOOL_REGISTRY`, so every task ends immediately after the first LLM turn.

---

## Symptom → cause reference

| Symptom | Most likely cause |
|---|---|
| `JSONDecodeError` during `json.loads` | Parsing arguments mid-stream instead of after the stream ends |
| Tool executes with `None` for a required argument | `json.loads` succeeded on a truncated buffer; argument key is absent in the partial JSON |
| `tool_call_id` is `None` in the tool result message | `id` overwritten by a later chunk that carries `id=None` |
| Agent stops after first LLM turn, ignores tool calls | Checking for `finish_reason == "tool_use"` instead of `"tool_calls"` |
| Multiple tool calls produce garbled arguments | Accumulating by list position instead of by `index` |
| Second tool call has `name=""` | `name` overwritten to `None` from a later chunk, then stored as empty string |
| Agent hangs after tool execution, no further output | Tool result message missing `tool_call_id` or using wrong role (e.g. `"user"` instead of `"tool"`) |
| Loop exits after one tool call even when more are pending | `has_more_tool_calls` set to `False` before checking `tool_acc` — `finish_reason` check fires too early |
| Blocking tool execution prevents other tools from running | Async tool not wrapped in `await asyncio.to_thread(...)` — event loop is blocked |

---

## Related pages

- [Architecture: Streaming & Events](../architecture/streaming-and-events.md) — the accumulation data flow and why buffer-then-parse is mandatory
- [Architecture: The Agent Loop](../architecture/the-agent-loop.md) — Phases A–E and where each chunk type is handled
