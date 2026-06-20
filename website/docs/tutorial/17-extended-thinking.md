---
sidebar_position: 18
title: "Phase 17 — Extended Thinking"
description: Give the model explicit scratchpad space before it answers — a separate reasoning trace useful for hard multi-step problems.
---

# Phase 17 — Extended Thinking

:::note Starting point
The agent with context compaction from Phase 16. It handles long sessions without hitting the context limit. For hard multi-step problems, the model may still benefit from explicit reasoning before committing to an action.
:::

Extended thinking gives the model scratchpad space — a `ThinkingContent` block that appears before the text response or tool call. The model works through the problem in the scratchpad before it commits. This is useful when the task requires multi-step planning before any tool call makes sense, or when the model keeps making the wrong choice between approaches and you want to see why.

V1 skips it: the agent works well without it for routine coding tasks. This phase adds it for the cases where it earns its keep.

:::note
Extended thinking is a **planned extension**, not part of v1. The current `stream_response()` call does not pass the `thinking` parameter, and the streaming accumulation in `agent.py` does not handle `ThinkingContent` blocks. Adding it requires changes in both `provider.py` and `agent.py`. See the full design at [Extended Thinking](../advanced/extended-thinking.md).
:::

## What you'll learn

- What the model produces when extended thinking is enabled: a `ThinkingContent` block before each `TextContent` or `ToolUseContent` block, and why the block order matters.
- How to enable thinking via `litellm.acompletion`'s `thinking` parameter, and why `max_tokens` must be increased when you do.
- How to accumulate the thinking stream in a separate `thinking_buf` alongside the existing `text_buf` in `agent.py`.
- How thinking blocks must be preserved verbatim in message history (they count against the context window and must not be dropped or summarised between turns).

## Build it

Enable thinking in `provider.py`:

```python
# src/provider.py — with extended thinking (planned)
response = await litellm.acompletion(
    model="claude-sonnet-4-5",
    messages=full_messages,
    tools=TOOLS_SCHEMA,
    tool_choice="auto",
    max_tokens=16000,        # must exceed budget_tokens
    thinking={
        "type": "enabled",
        "budget_tokens": 8000,
    },
    stream=True,
)
```

:::warning
`max_tokens` must be larger than `budget_tokens`. The v1 default of 8,096 in `provider.py` is not enough — increase it when enabling thinking. If `budget_tokens` is 8,000, set `max_tokens` to at least 10,000.
:::

In `agent.py`, add a `thinking_buf` alongside the existing `text_buf`:

```python
# src/agent.py — accumulation with thinking (planned)
text_buf = ""
thinking_buf = ""   # new
tool_acc: dict[int, dict] = {}

async for chunk in stream_response(messages, system_prompt):
    delta = chunk.choices[0].delta

    if hasattr(delta, "thinking") and delta.thinking:
        thinking_buf += delta.thinking
        # emit to a debug channel, not main stdout

    if delta.content:
        text_buf += delta.content
        print(delta.content, end="", flush=True)

    if delta.tool_calls:
        # ... existing accumulation unchanged ...
```

The assistant message must preserve thinking blocks verbatim — block order matters (thinking before text/tool_use), and the `signature` field must be echoed back as received:

```python
# With thinking (planned)
assistant_msg = {
    "role": "assistant",
    "content": [
        {"type": "thinking", "thinking": thinking_buf},  # must be first
        {"type": "text", "text": text_buf},
    ],
    "tool_calls": tool_calls,
}
```

For the full streaming shape, the `signature` field detail, and guidance on when extended thinking helps versus when the overhead isn't worth it, see [Extended Thinking](../advanced/extended-thinking.md).

## Test it

### Behavior (BDD)

Verify this phase as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Scenario: Extended thinking produces a reasoning trace before the final answer
  Given extended thinking is enabled with a budget of 8000 tokens
  And the agent is given a multi-step planning problem
  When the agent runs to completion
  Then the assistant message history contains a thinking block before the text block
  And the final answer reflects reasoning established in the thinking block
```

Run this as an integration scenario with the [BDD framework](../guides/bdd-integration-testing.md). Script a `ScriptedLLM` turn that includes a `thinking` field on the delta alongside the usual `content`. Assert that `assistant_msg["content"]` is a list, that the first element has `type == "thinking"`, and that the `thinking_buf` captured during accumulation is non-empty.

## Run it

Manual verification:

1. Enable extended thinking in `provider.py` with `budget_tokens=2000` and `max_tokens=4000` (a small budget is enough to verify the plumbing).
2. Run the agent on a problem that benefits from planning: `uv run main.py "refactor the tools module so each tool is in its own file"`.
3. Inspect the raw message history after the run — confirm the first assistant message has a `content` list starting with `{"type": "thinking", ...}`.
4. Optionally emit `thinking_buf` to a debug log and confirm the model's reasoning trace is coherent and non-empty.

## Recap

After this phase the agent can use extended thinking for hard multi-step problems. The reasoning trace appears in a separate `ThinkingContent` block before each response, is preserved verbatim in message history, and does not appear in the user-facing stdout stream. For routine tasks, leave thinking disabled — the overhead (cost, context pressure) is not worth it.

Next: [Phase 18 — Go Further & Close](./18-go-further.md), the final phase — BDD integration testing, architecture patterns, and closing the tutorial.
