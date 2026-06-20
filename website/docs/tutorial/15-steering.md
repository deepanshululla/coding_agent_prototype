---
sidebar_position: 16
title: "Phase 15 — Steering"
description: After the agent finishes a task, inject a follow-up message into the outer loop to redirect it without replaying the whole conversation.
---

# Phase 15 — Steering

:::note Implemented
This step is implemented on branch `step/phase-15-steering` (plan: `plans/tutorial/phase-15-steering.md`).
:::

:::note Starting point
The fully interfaced agent from Phase 14. It has a terminal UI, an SDK, RPC mode, and a JSON event stream. You have a complete, hardened, extensible, multi-interface coding agent.
:::

The agent finishes a task and stops. Steering is what lets you say "actually, also run the tests" — and have the agent continue from where it left off, without re-running any of the prior tool calls or re-sending the full conversation from scratch.

This is not a new outer wrapper or a second `run_agent` call. The mechanism is already present in `agent.py`: the `pending_messages` list and the two-level loop structure. Steering makes that mechanism live.

:::note
Steering is a **planned extension** to the v1 agent. The `pending_messages` list and outer loop exist in `agent.py` today. What's missing is the mechanism to push messages into `pending_messages` from outside the loop while it's running. See the full design at [Steering Messages](../advanced/steering.md).
:::

## What you'll learn

- How the outer loop / inner loop structure in `agent.py` supports steering without architectural changes.
- The three implementation options (asyncio.Queue, between-tool-call polling, external signal via RPC) and the tradeoffs of each.
- How `pending_messages` is flushed at each inner-loop iteration so that a message injected after a tool batch is seen before the next model call.
- How to pass a `get_steering_messages` callable into `run_agent` so the caller controls the input channel.

## Build it

The outer loop in `agent.py` currently ends with an unconditional `break`:

```python
# src/agent.py — current v1 outer loop ending
break  # no follow-up support in v1
```

Replace that `break` with a check for new `pending_messages`, and the outer loop becomes a real steering channel. At each inner-loop iteration, the existing flush already handles them:

```python
if pending_messages:
    messages.extend(pending_messages)
    pending_messages.clear()
```

The cleanest extension is an injected async callable — `get_steering_messages` — that the caller provides:

```python
async def run_agent(
    task: str,
    get_steering_messages=None,   # async () -> list[dict]
) -> None:
    ...
    while (has_more_tool_calls or pending_messages) and iteration < MAX_ITERATIONS:
        if get_steering_messages:
            new_msgs = await get_steering_messages()
            pending_messages.extend(new_msgs)
        ...
```

The caller supplies any implementation — a stdin reader, an asyncio.Queue consumer, or a no-op. The agent loop sees only a list of messages; it doesn't care where they came from.

For the full design — including the asyncio.Queue approach, the between-tool-call polling option, and the RPC external signal approach — see [Steering Messages](../advanced/steering.md).

## Test it

### Behavior (BDD)

Verify this phase as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Scenario: Steering continues the agent without replaying prior tool calls
  Given the agent has completed a task using read_file and write_file
  When a follow-up message is injected via the steering API asking to run the tests
  Then the agent continues from where it left off
  And the prior read_file and write_file calls are not replayed
  And the agent executes a bash tool call for the test run
```

Run this as an integration scenario with the [BDD framework](../guides/bdd-integration-testing.md). Script two phases of turns: a first block ending with `finish_reason="stop"`, then supply a steering message via `get_steering_messages`, and script a second block where the agent runs `bash`. Assert that the `read_file` and `write_file` calls appear only once in `agent_world.tool_calls`, and that a `bash` call appears after them.

## Run it

Manual verification:

1. Run the agent on a small task: `uv run main.py "create a file called hello.py with a hello function"`.
2. After it finishes, inject a steering follow-up via the configured channel (stdin, queue, or the SDK's `steer()` method).
3. Confirm the agent resumes and completes the follow-up task.
4. Inspect the message history: the prior tool calls must not be re-executed — only the new task's turns appear after the steering message.

:::tip Architecture pattern
Steering turns the loop into a [State Machine](../architecture-patterns/state-machine.md) with a re-plan transition, and is the feedback path of a [Planner / Executor](../architecture-patterns/planner-executor.md) split.
:::

## Recap

After this phase the agent accepts mid-session redirects via `pending_messages`, powered by an injected `get_steering_messages` callable. The outer loop reuses the existing two-level structure; no new loop was added.

Next: [Phase 16 — Context Compaction](./16-context-compaction.md) — as the steered session grows, the context window fills. Compaction summarizes old turns into a compressed representation that preserves essential facts while reclaiming tokens.
