---
sidebar_position: 3
title: Streaming & Event Accumulation
description: How LiteLLM streaming chunks are structured, why tool-call arguments must be buffered by index, and the gotchas that will burn you if you skip this page.
---

# Streaming & Event Accumulation

Streaming from an LLM is not like receiving a complete JSON response. You get a sequence of small chunks, each carrying a fragment of the final output. Text arrives word by word. Tool call arguments arrive as partial JSON strings split across many chunks. You have to accumulate everything before you can act on it.

This page explains the exact shape of each chunk, how to accumulate tool calls correctly, and the gotchas that cause silent bugs.

:::note
The accumulation code shown here is the planned implementation from `PLAN.md`, reflected in `src/agent.py` which is not yet fully implemented.
:::

## Chunk structure (OpenAI format)

LiteLLM normalizes all provider responses to OpenAI's streaming format. Every chunk has the same top-level shape:

```python
chunk.choices[0].delta.content          # str | None — a text fragment
chunk.choices[0].delta.tool_calls       # list[ToolCallChunk] | None
chunk.choices[0].finish_reason          # "stop" | "tool_calls" | None
```

A single chunk carries either a text fragment, tool call fragments, or neither (intermediate chunk with only metadata). Rarely both text and tool calls in the same chunk.

### Tool call chunk shape

When `delta.tool_calls` is not `None`, it is a list of `ToolCallChunk` objects:

```python
tc_chunk.index              # int — which tool call this fragment belongs to
tc_chunk.id                 # str | None — only present on the FIRST chunk for this index
tc_chunk.function.name      # str | None — only present on the FIRST chunk for this index
tc_chunk.function.arguments # str | None — partial JSON string fragment
```

The model can request multiple tool calls in a single turn. Each has its own `index` (0, 1, 2, ...). Fragments for different tool calls can interleave.

## The accumulation pattern

The correct approach is to maintain a buffer keyed by `index`, accumulate all fragments during streaming, then finalize after the stream ends:

```python
text_buf = ""
# tool_acc: index → {id, name, arguments_buf}
tool_acc: dict[int, dict] = {}
finish_reason = None

async for chunk in stream_response(messages, system_prompt):
    delta = chunk.choices[0].delta
    finish_reason = chunk.choices[0].finish_reason or finish_reason

    # Text fragment — print immediately for live output
    if delta.content:
        text_buf += delta.content
        print(delta.content, end="", flush=True)

    # Tool call fragments — buffer by index
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

# Stream is done. Now build finalized tool_calls and parse JSON.
tool_calls = [
    {
        "id": tc["id"],
        "type": "function",
        "function": {
            "name": tc["name"],
            "arguments": tc["arguments_buf"],  # keep as string for history
        },
    }
    for tc in tool_acc.values()
]

# Parse arguments only after the full stream completes
parsed_calls = [
    {
        "id": tc["id"],
        "name": tc["function"]["name"],
        "input": json.loads(tc["function"]["arguments"]),
    }
    for tc in tool_calls
]
```

`json.loads` appears exactly once — after the loop. Never inside it.

## What a streaming sequence looks like

Here is a concrete example of the chunk sequence when the model requests two tool calls:

```
chunk 1:  finish_reason=None, delta.content="I'll start by reading the file."
chunk 2:  finish_reason=None, delta.content=" Let me also check the directory."
chunk 3:  finish_reason=None, delta.tool_calls=[{index=0, id="call_abc", name="read_file", arguments=""}]
chunk 4:  finish_reason=None, delta.tool_calls=[{index=0, id=None, name=None, arguments='{"path"'}]
chunk 5:  finish_reason=None, delta.tool_calls=[{index=0, id=None, name=None, arguments=': "src/t'}]
chunk 6:  finish_reason=None, delta.tool_calls=[{index=0, id=None, name=None, arguments='ools.py"}'}]
chunk 7:  finish_reason=None, delta.tool_calls=[{index=1, id="call_def", name="list_dir", arguments=""}]
chunk 8:  finish_reason=None, delta.tool_calls=[{index=1, id=None, name=None, arguments='{"path"'}]
chunk 9:  finish_reason=None, delta.tool_calls=[{index=1, id=None, name=None, arguments=': "src"}'}]
chunk 10: finish_reason="tool_calls", delta.content=None, delta.tool_calls=None
```

After processing all 10 chunks:
- `tool_acc[0]` has `id="call_abc"`, `name="read_file"`, `arguments_buf='{"path": "src/tools.py"}'`
- `tool_acc[1]` has `id="call_def"`, `name="list_dir"`, `arguments_buf='{"path": "src"}'`

Both can now be safely passed to `json.loads`.

## Gotcha table

| Gotcha | What goes wrong if you ignore it | Correct behavior |
|--------|----------------------------------|-----------------|
| Tool arguments arrive as partial JSON fragments | Calling `json.loads` mid-stream raises `JSONDecodeError` on incomplete strings | Buffer `arguments_buf` by `index`; only `json.loads` after the stream ends |
| `id` and `name` only appear on the first chunk for each `index` | Overwriting with later `None` values clears the accumulated id/name | Guard with `if tc_chunk.id:` and `if tc_chunk.function and tc_chunk.function.name:` |
| Multiple tool calls per turn share the same stream | Processing sequentially by arrival order conflates fragments from different tool calls | Key the accumulator by `tc_chunk.index`, not by arrival order |
| `finish_reason` is `"tool_calls"`, not `"tool_use"` | Matching against Anthropic's raw event name misses the stop condition | LiteLLM uses OpenAI's value: `"tool_calls"` |
| `finish_reason` is `None` on most chunks | Taking the first non-`None` value loses all subsequent updates | Use `finish_reason = chunk.choices[0].finish_reason or finish_reason` to retain last non-None |
| Tool call `arguments` must stay as a string in message history | Storing a `dict` in the history breaks providers that expect the JSON string form | Pass `tc["arguments_buf"]` (string) to `"arguments"` in history; only `json.loads` for execution |
| Blocking I/O inside async tools blocks the event loop | File reads and subprocess calls freeze the loop while executing | Wrap blocking calls with `await asyncio.to_thread(fn, *args)` inside each tool |

## Why not parse arguments as they arrive?

The `function.arguments` field carries a JSON string split across an arbitrary number of chunks. There is no guarantee about where the splits happen — you might get `'{"pa'` then `'th":'` then `' "src"}`. Calling `json.loads` on any of those fragments raises an exception.

Even if you checked `json.loads` defensively and caught `JSONDecodeError`, you would not know whether you have a partial fragment or a malformed argument. Buffer first, parse once.

## Contrast with raw Anthropic events

If you call the Anthropic SDK directly (without LiteLLM), the streaming event model is different:

```python
# Raw Anthropic SDK events (NOT what this project uses)
event.type == "content_block_start"   # signals start of a new block
event.type == "content_block_delta"   # carries text or input_json_delta
event.type == "content_block_stop"    # signals end of block
event.content_block.type == "tool_use"
event.delta.type == "input_json_delta"
event.delta.partial_json              # the partial argument string
```

LiteLLM hides all of that. You always see `delta.tool_calls[i].function.arguments` regardless of the underlying provider. The buffering logic above works for Anthropic, OpenAI, Gemini, and any other LiteLLM-supported model.

## Related pages

- [The Agent Loop](./the-agent-loop.md) — where this accumulation code lives (Phase A)
- [Message Types](./message-types.md) — the finalized shapes that go into message history after accumulation
- [The Provider Layer](./provider-layer.md) — what yields the chunks in the first place
