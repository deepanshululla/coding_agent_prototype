---
sidebar_position: 2
title: The Context Window
description: How the messages list grows each turn, what the 200k token limit means in practice, and why long tool outputs are truncated before they hit the model.
---

# The Context Window

Every LLM call has a context window — a finite buffer of tokens the model can see at once. Everything the model knows about your task must fit inside it. Understanding the context window helps you reason about why the agent truncates outputs, why long sessions eventually fail, and how compaction works as a mitigation.

## What lives in the context window

The agent maintains a single `messages` list. On each loop iteration, the entire list is sent to the model. It grows in one direction only — items are appended, never removed (in v1).

At any point in a session, the messages list contains:

| Message type | Role | When added |
|---|---|---|
| Initial user task | `"user"` | Once, at session start |
| Assistant text + tool call requests | `"assistant"` | After each streaming response |
| Tool results | `"tool"` | One per tool call, after parallel execution |
| Follow-up user messages | `"user"` | When `pending_messages` are flushed (outer loop) |

The system prompt is prepended on every call but is **not** stored in `messages`. It is constant for the session, so it benefits from prefix caching on providers that support it.

## The 200k token limit

Claude models support up to 200,000 tokens of context. That sounds large, but it fills up faster than you expect in a coding session:

- A 1,000-line Python file is roughly 5,000–8,000 tokens.
- A `bash` output from running a test suite with verbose output can be 2,000–5,000 tokens.
- Ten back-and-forth tool call cycles might consume 20,000–50,000 tokens.

A long debugging session — read files, run tests, edit, re-run, read logs — can hit the limit within 20–30 iterations.

:::warning
When the context exceeds the model's limit, `litellm.acompletion` raises an error. The agent does not handle this gracefully in v1 — it crashes. Compaction is the planned mitigation.
:::

## Why tool outputs are truncated

Raw tool output can be enormous. A `bash` command like `find . -name "*.py"` on a large monorepo might return thousands of lines. A `grep` across a codebase might return megabytes of matches. Feeding that directly into the context would exhaust the window in a single turn.

The agent applies hard limits before appending tool results:

| Tool | Truncation rule |
|---|---|
| `bash` | Output capped at **10,000 characters** |
| `find_files` | Results limited to **200 entries** |
| `read_file` | Accepts `offset` and `limit` params (default: 2,000 lines) |

These limits are enforced inside the tool implementations in `src/tools.py`, not in the loop itself. The truncated result is what gets appended to `messages` — the model never sees the rest.

:::note
These limits are enforced by the constants `BASH_OUTPUT_LIMIT = 10_000`, `FIND_LIMIT = 200`, and `read_file`'s `limit` parameter (default `2000`) in `src/tools.py`.
:::

When output is truncated, the model sees only the first N characters/results. It may need to call the tool again with narrower parameters (e.g., `read_file` with an `offset`) to see more. The guidelines in the system prompt encourage the model to do exactly this.

## What counts toward context

Everything in `full_messages` at call time:

```python
full_messages = [{"role": "system", "content": system_prompt}] + messages
```

This includes:

- The system prompt (constant, ~400 tokens for the default template)
- All prior assistant turns — including their `tool_calls` arrays (the JSON argument strings count)
- All tool result messages — including full content strings after truncation
- All user messages

Tool call argument JSON is stored as a string in message history (not a parsed dict), which is correct per the OpenAI format but adds a small overhead per tool call.

## Growth pattern across a session

Here is a simplified view of how the messages list grows across three iterations:

```
Start:
  messages = [
    {"role": "user", "content": "Add type hints to tools.py"}
  ]

After iteration 1 (model calls read_file):
  messages = [
    {"role": "user",      "content": "Add type hints to tools.py"},
    {"role": "assistant", "content": null, "tool_calls": [...]},
    {"role": "tool",      "tool_call_id": "...", "content": "<file contents>"}
  ]

After iteration 2 (model calls edit_file):
  messages = [
    ... (all prior messages) ...,
    {"role": "assistant", "content": null, "tool_calls": [...]},
    {"role": "tool",      "tool_call_id": "...", "content": "Edit applied."}
  ]

After iteration 3 (model calls bash to verify):
  messages = [
    ... (all prior messages) ...,
    {"role": "assistant", "content": null, "tool_calls": [...]},
    {"role": "tool",      "tool_call_id": "...", "content": "... test output ..."},
    {"role": "assistant", "content": "Done. All functions now have type hints."}
  ]
```

Each iteration adds at minimum two messages (one assistant turn plus one or more tool results). Long sessions accumulate fast.

## Compaction

When the context grows large, the solution is compaction: summarize the earlier portion of the message history into a single compact message, then replace it. This shrinks the token count while preserving the relevant facts.

Compaction is not implemented in v1. See [Compaction](../advanced/compaction.md) for how it works and when to add it.
