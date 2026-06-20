---
sidebar_position: 2
title: Context Compaction
description: What to do when the agent's message history approaches the model's context limit, and where a compaction hook slots into the loop.
---

# Context Compaction

:::tip Verify
Run the agent on a long task until the history exceeds the compaction threshold; confirm the compacted history is shorter and the agent continues coherently.
:::

Every message in the agent's history — the initial task, every assistant turn, every tool call and its result — accumulates tokens. Claude has a 200k-token context window. A long coding session with many file reads, bash outputs, and back-and-forth can fill it.

When the context limit is hit, the API returns an error and the agent stops. Compaction is the strategy for preventing that: shrinking old history before it overflows, while keeping enough context that the model can still do useful work.

:::note
Context compaction is a **planned feature**, not part of v1. The current agent has no compaction logic — `messages` grows without bound until an API error occurs. This page documents the design and where a compaction hook would slot into the loop.
:::

See also: [Context Window](../concepts/context-window.md) for how tokens are counted and what contributes most to history growth.

## Why it's needed

A typical inner-loop iteration adds:

- One assistant message (text + tool_calls list)
- N tool result messages (one per parallel tool call)

`bash` outputs are truncated at 10,000 characters. `read_file` returns up to 2,000 lines. A single iteration reading several large files can add tens of thousands of tokens. With `MAX_ITERATIONS = 30`, the worst case is well over 200k tokens.

## Pi's `transformContext` hook

Pi's agent core calls a `transformContext(messages)` hook at the top of each inner-loop iteration, before sending to the API. The hook receives the full history and returns a (possibly shorter) history. The agent sends whatever `transformContext` returns — it never sees the original list.

```typescript
// pi's pattern (TypeScript — for reference)
const contextToSend = await transformContext(messages);
const response = await sendMessage(contextToSend, systemPrompt);
```

The Python equivalent is a pre-send step in the inner loop:

```python
# Where compaction would slot in — top of inner loop, before stream_response
context_to_send = await compact_if_needed(messages, system_prompt)
async for chunk in stream_response(context_to_send, system_prompt):
    ...
```

Note: `messages` (the source of truth) is never mutated by compaction. You send a compacted snapshot; the full history stays intact for future compaction decisions.

## Compaction strategies

### Strategy 1 — Summarise old turns

Replace a block of old assistant + tool messages with a single summary message:

```python
async def compact_if_needed(messages: list[dict], system_prompt: str) -> list[dict]:
    if estimate_tokens(messages) < TOKEN_BUDGET:
        return messages  # no compaction needed

    # Keep first user message + last N turns; summarise the middle
    head = messages[:1]           # original task
    tail = messages[-KEEP_TURNS:]  # recent context
    middle = messages[1:-KEEP_TURNS]

    summary_text = await summarise(middle)  # LLM call to summarise
    summary_msg = {"role": "user", "content": f"[Summary of earlier work]\n{summary_text}"}

    return head + [summary_msg] + tail
```

Tradeoffs: preserves semantic content; costs an extra LLM call; summary may lose details the agent needs.

### Strategy 2 — Drop stale tool outputs

Tool results from early in the session are often irrelevant by the time the agent is 20 iterations deep. Drop them while keeping the tool_call entries (so the model still knows which tools were called):

```python
def drop_old_tool_results(messages: list[dict], keep_recent: int = 10) -> list[dict]:
    tool_result_indices = [i for i, m in enumerate(messages) if m["role"] == "tool"]
    stale = set(tool_result_indices[:-keep_recent])
    return [m for i, m in enumerate(messages) if i not in stale]
```

Tradeoffs: fast, no LLM call; the model loses access to old tool content but retains the call history; works well when file contents change across iterations anyway.

### Strategy 3 — Keep system prompt + recent turns only

The most aggressive strategy: discard everything except the system prompt and the last K turns. Effective when the task is narrow and self-contained within recent context.

```python
def keep_recent_only(messages: list[dict], keep_turns: int = 5) -> list[dict]:
    return messages[-keep_turns * 2:]  # each turn = assistant + tool results
```

Tradeoffs: no LLM call; loses all early context; the model may repeat work it already did.

## Where the hook slots into `agent.py`

The inner loop in `agent.py` currently calls `stream_response(messages, system_prompt)` directly. Adding a compaction hook requires one line of indirection:

```python
# src/agent.py — inner loop (planned)
while (has_more_tool_calls or pending_messages) and iteration < MAX_ITERATIONS:
    iteration += 1

    if pending_messages:
        messages.extend(pending_messages)
        pending_messages.clear()

    # ── Compaction hook (planned) ─────────────────────────────────
    context_to_send = await compact_if_needed(messages, system_prompt)
    # ─────────────────────────────────────────────────────────────

    text_buf = ""
    tool_acc: dict[int, dict] = {}
    finish_reason = None

    async for chunk in stream_response(context_to_send, system_prompt):
        ...
```

`compact_if_needed` is a no-op until the token budget is exceeded; it returns `messages` unchanged. This makes it safe to add before the feature is implemented.

## Token estimation

You need an estimate before the API call fails. Two options:

**Option A — tiktoken / anthropic tokenizer:**

```python
import anthropic

client = anthropic.Anthropic()

def estimate_tokens(messages: list[dict], system_prompt: str) -> int:
    # Anthropic's beta token-counting endpoint
    response = client.beta.messages.count_tokens(
        model="claude-sonnet-4-5",
        system=system_prompt,
        messages=messages,
        tools=TOOLS_SCHEMA,
    )
    return response.input_tokens
```

This is exact but requires an API call.

**Option B — character heuristic:**

```python
import json

def estimate_tokens(messages: list[dict]) -> int:
    total_chars = sum(len(json.dumps(m)) for m in messages)
    return total_chars // 4  # rough: ~4 chars per token
```

Fast, free, underestimates structured JSON. Good enough for a trigger threshold with a generous safety margin (e.g. trigger at 150k estimated tokens, well below the 200k hard limit).

## Recommended thresholds

| Threshold | Action |
|-----------|--------|
| < 100k tokens | No compaction |
| 100k–160k tokens | Drop stale tool results |
| 160k–190k tokens | Summarise old turns |
| > 190k tokens | Keep recent turns only (emergency) |

These are starting points; tune for your typical task length and tool output sizes.

## Related pages

- [Context Window](../concepts/context-window.md) — what consumes tokens and how to monitor growth
- [Steering Messages](./steering.md) — mid-run injection that adds turns and accelerates context growth
- [The Agent Loop](../architecture/the-agent-loop.md) — where compaction slots into the iteration
