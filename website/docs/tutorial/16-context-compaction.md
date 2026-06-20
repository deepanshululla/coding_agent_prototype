---
sidebar_position: 17
title: "Phase 16 — Context Compaction"
description: As the message history grows, the context window fills. Compaction summarizes old turns into a compressed representation that preserves essential facts while reclaiming tokens.
---

# Phase 16 — Context Compaction

:::note Starting point
The steerable agent from Phase 15. It accepts mid-session redirects via `pending_messages`. Steering sessions can run long — and long sessions fill the context window.
:::

Every message in the agent's history accumulates tokens: the initial task, every assistant turn, every tool call, every result. Claude has a 200k-token context window. A long coding session with many file reads, bash outputs, and steering follow-ups can fill it.

When the context limit is hit, the API returns an error and the agent stops dead. Compaction prevents that: it shrinks old history before it overflows, while keeping enough context that the model can still do useful work.

:::note
Context compaction is a **planned feature**, not part of v1. The current agent has no compaction logic — `messages` grows without bound until an API error occurs. This page describes the design and where the compaction hook slots into the loop. See the full design at [Context Compaction](../advanced/compaction.md).
:::

## What you'll learn

- Why the context window fills and what consumes tokens fastest (file reads, bash output, steering turns).
- The `transformContext` / `compact_if_needed` hook pattern: a pre-send step in the inner loop that returns a (possibly shorter) history without mutating the source-of-truth `messages` list.
- Three compaction strategies — summarise old turns (LLM call), drop stale tool outputs (no LLM call), keep recent turns only (emergency) — and when each is appropriate.
- How to estimate tokens cheaply before the API call fails, and recommended thresholds for triggering each strategy.

## Build it

Compaction slots into the inner loop in `agent.py` as a single indirection before `stream_response`:

```python
# src/agent.py — inner loop (planned)
while (has_more_tool_calls or pending_messages) and iteration < MAX_ITERATIONS:
    iteration += 1

    if pending_messages:
        messages.extend(pending_messages)
        pending_messages.clear()

    # ── Compaction hook ───────────────────────────────────────────
    context_to_send = await compact_if_needed(messages, system_prompt)
    # ─────────────────────────────────────────────────────────────

    async for chunk in stream_response(context_to_send, system_prompt):
        ...
```

`messages` is never mutated by compaction — it remains the full source of truth. `compact_if_needed` returns `messages` unchanged until the token budget is exceeded, so it is safe to add before the feature is implemented.

The recommended threshold ladder:

| Estimated tokens | Strategy |
|-----------------|----------|
| < 100k | No compaction — return messages unchanged |
| 100k–160k | Drop stale tool results — fast, no extra LLM call |
| 160k–190k | Summarise old turns — semantic, costs one LLM call |
| > 190k | Keep recent turns only — emergency; model may repeat work |

For the full strategy implementations, token estimation options, and the pi `transformContext` pattern this mirrors, see [Context Compaction](../advanced/compaction.md).

## Test it

### Behavior (BDD)

Verify this phase as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Scenario: Compaction keeps the agent coherent after a long task
  Given a long task whose message history exceeds the compaction threshold
  When the agent continues after compaction triggers
  Then the context sent to the model is shorter than the full message history
  And the agent proceeds coherently without losing the essential facts from prior turns
```

Run this as an integration scenario with the [BDD framework](../guides/bdd-integration-testing.md). Script enough turns to exceed the threshold (patch the threshold to a low value in tests), monkeypatch `compact_if_needed` to record when it fires, assert that `len(context_to_send) < len(messages)` after the trigger turn, and assert that the final answer still references a fact established early in the conversation.

## Run it

Manual verification:

1. Configure a low compaction threshold (e.g. patch `TOKEN_BUDGET = 500` for a short test run).
2. Run the agent on a task that produces several tool results: `uv run main.py "read three files and summarize them"`.
3. After the run, inspect the history length before and after the compaction turn.
4. Confirm that the compacted history is shorter than the pre-compaction history.
5. Ask the agent a follow-up question that requires a fact from early in the session; confirm it answers correctly.

:::tip Architecture pattern
Compaction at phase boundaries pairs with the [Planner / Executor](../architecture-patterns/planner-executor.md) split and an [event-sourced](../architecture-patterns/event-sourcing.md) history you can re-derive.
:::

## Recap

After this phase the agent handles long sessions without hitting the 200k-token context limit. The `compact_if_needed` hook compresses old history while preserving the source-of-truth `messages` list. The model never sees the compaction happening.

Next: [Phase 17 — Extended Thinking](./17-extended-thinking.md) — give the model explicit scratchpad space before it answers, for hard multi-step problems where it benefits from working things out before committing to an action.
