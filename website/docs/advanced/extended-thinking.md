---
sidebar_position: 3
title: Extended Thinking
description: How Anthropic's extended thinking (reasoning tokens) would flow through the streaming loop and message history, and why v1 skips it.
---

# Extended Thinking

:::tip Verify
Enable extended thinking and run a multi-step problem; confirm the model's reasoning trace appears and the final answer reflects it.
:::

Extended thinking is an Anthropic feature where the model performs explicit chain-of-thought reasoning before generating its response. The reasoning appears as a separate content block (`ThinkingContent`) in the response — distinct from the text the agent prints and the tool calls it makes.

V1 skips it. The agent works well without it for most coding tasks. This page explains what extended thinking is, how it would flow through the streaming accumulation and message history, and when it's worth adding.

:::note
Extended thinking is a **planned extension**, not part of v1. The current `stream_response()` call does not pass the `thinking` parameter, and the streaming accumulation in `agent.py` does not handle `ThinkingContent` blocks. Adding it requires changes in both `provider.py` and `agent.py`.
:::

## What extended thinking produces

When enabled, the model's response contains two block types instead of one:

```
[ThinkingContent block]   ← reasoning tokens (not shown to end users by default)
[TextContent block]       ← the model's actual response text
```

Or, if the model decides to call a tool:

```
[ThinkingContent block]   ← reasoning about which tool to call and why
[ToolUseContent block]    ← the tool call
```

The thinking content is the model "working through" the problem before committing to a response. It's useful for hard multi-step problems — complex refactors, debugging mysterious failures, planning a sequence of tool calls.

## How to enable it

Pass `thinking` to `litellm.acompletion`:

```python
# src/provider.py — with extended thinking (planned)
response = await litellm.acompletion(
    model="claude-sonnet-4-5",
    messages=full_messages,
    tools=TOOLS_SCHEMA,
    tool_choice="auto",
    max_tokens=16000,        # must be higher when thinking is on; thinking tokens count toward max
    thinking={
        "type": "enabled",
        "budget_tokens": 8000,   # max tokens the model can spend on reasoning
    },
    stream=True,
)
```

`budget_tokens` controls how much the model can think before it has to produce output. Higher budgets help on harder problems; lower budgets save cost.

:::warning
`max_tokens` must be larger than `budget_tokens`. If `budget_tokens` is 8,000, `max_tokens` must be at least 8,001 (plus however many output tokens you want). The model's default of 8,096 in `provider.py` is not enough — increase it when enabling thinking.
:::

## How thinking blocks flow through streaming

In LiteLLM's OpenAI-format chunks, thinking content arrives similarly to text content, but with a different block type. The exact chunk structure depends on LiteLLM's normalization for `claude-sonnet-4-5`; at the raw Anthropic level, thinking blocks arrive as:

```
content_block_start  { type: "thinking" }
content_block_delta  { type: "thinking_delta", thinking: "..." }
content_block_stop
content_block_start  { type: "text" }
content_block_delta  { type: "text_delta", text: "..." }
content_block_stop
```

In the streaming accumulation loop in `agent.py`, you need to buffer thinking content separately from text content:

```python
# src/agent.py — accumulation with thinking (planned)
text_buf = ""
thinking_buf = ""   # new
tool_acc: dict[int, dict] = {}
finish_reason = None

async for chunk in stream_response(messages, system_prompt):
    delta = chunk.choices[0].delta
    finish_reason = chunk.choices[0].finish_reason or finish_reason

    # Check for thinking content (LiteLLM normalization may vary)
    if hasattr(delta, "thinking") and delta.thinking:
        thinking_buf += delta.thinking
        # optionally emit to a debug channel, not main stdout

    if delta.content:
        text_buf += delta.content
        print(delta.content, end="", flush=True)

    if delta.tool_calls:
        # ... existing tool_call accumulation ...
```

:::tip
LiteLLM's exact field for thinking content may differ from raw Anthropic events. Check `chunk.choices[0].delta` carefully when implementing — print a few raw chunks first to see the actual shape.
:::

## How thinking blocks appear in message history

Anthropic's API requires that thinking blocks be preserved in message history exactly as they were received — you can't summarise or drop them without losing the model's reasoning chain. The assistant message must carry the full block list:

```python
# Without thinking (v1)
assistant_msg = {
    "role": "assistant",
    "content": text_buf or None,
    "tool_calls": tool_calls,  # if any
}

# With thinking (planned)
assistant_msg = {
    "role": "assistant",
    "content": [
        {"type": "thinking", "thinking": thinking_buf},  # must be first
        {"type": "text", "text": text_buf},              # if present
    ],
    "tool_calls": tool_calls,  # if any
}
```

The block order matters: thinking must precede text and tool_use blocks. Sending history with blocks out of order returns an API error.

This also means thinking content **counts against the context window** across turns. A 8,000-token thinking block in turn 1 appears in full in every subsequent API call. For long sessions, this accelerates context growth — see [Context Compaction](./compaction.md).

## Pi's `ThinkingContent` type

Pi's TypeScript type hierarchy has `ThinkingContent` alongside `TextContent` and `ToolUseContent`:

```typescript
type ContentBlock =
  | { type: "text"; text: string }
  | { type: "thinking"; thinking: string; signature: string }
  | { type: "tool_use"; id: string; name: string; input: object };
```

The `signature` field is an Anthropic-internal integrity token that must be echoed back verbatim. In LiteLLM, this is handled transparently if you pass the raw block dicts back in message history without modifying them.

In Python, the equivalent is to store raw dicts rather than parsing into `ThinkingContent` dataclasses — simpler and avoids round-trip serialisation bugs.

## Why v1 skips it

| Reason | Detail |
|--------|--------|
| Complexity | The streaming accumulation needs to track a third buffer; the message history format changes from a string to a block list |
| Cost | Thinking tokens are billed at standard input/output rates; a 8k budget per turn adds up quickly |
| Context pressure | Thinking blocks stay in history across turns — a 30-iteration session with 8k thinking tokens per turn adds 240k tokens of reasoning to the context |
| Not needed for most tasks | File operations, search, and code edits don't benefit much from extended reasoning; the model is effective without it |

## When it helps

Extended thinking is worth enabling when:

- The task requires multi-step planning before any tool call makes sense (e.g. "refactor this entire module to use a new interface")
- The agent keeps making the wrong choice between tools or approaches — extended thinking exposes why
- You're debugging a complex bug where the evidence is spread across many files and the model needs to synthesise it
- You're asking the agent to evaluate tradeoffs rather than just execute steps

For routine coding tasks — add a function, fix a test, rename a variable — the overhead isn't worth it.

## Related pages

- [Context Compaction](./compaction.md) — thinking blocks inflate history; compaction becomes more important
- [The Agent Loop](../architecture/the-agent-loop.md) — where the streaming accumulation happens
- [Provider Layer](../architecture/provider-layer.md) — `stream_response()` and `litellm.acompletion` parameters
