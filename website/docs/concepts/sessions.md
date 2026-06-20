---
sidebar_position: 5
title: Sessions & Conversation State
description: What a session is, how conversation state is held in memory for one run, how pending_messages extend a session via the outer loop, and what persisting a session would require.
---

# Sessions & Conversation State

A session is the agent's memory for a single run. It is the `messages` list that grows as the agent and model exchange turns. Understanding what a session is — and what it is not — helps you reason about statefulness, follow-up interactions, and the limits of v1.

:::note
`src/agent.py` is planned but not yet implemented. The design described here reflects the intended behavior from `PLAN.md`.
:::

## A session is the messages list

When `run_agent(task)` starts, it initializes the session with one message:

```python
messages: list[dict] = [{"role": "user", "content": task}]
```

Everything that follows — assistant turns, tool calls, tool results, follow-up user messages — is appended to this list. The list is what gets sent to the model on every iteration. The model has no memory outside of it.

```python
# State after a typical 3-iteration session:
messages = [
    {"role": "user",      "content": "Add docstrings to all functions in tools.py"},
    {"role": "assistant", "content": None, "tool_calls": [...]},
    {"role": "tool",      "tool_call_id": "call_1", "content": "<file contents>"},
    {"role": "assistant", "content": None, "tool_calls": [...]},
    {"role": "tool",      "tool_call_id": "call_2", "content": "Edit applied."},
    {"role": "assistant", "content": "Done. All functions now have docstrings."},
]
```

The `messages` list is the complete session. There is no database, no file, no cache — just this in-memory list. When `run_agent` returns, the session is gone.

## Pending messages and the outer loop

The agent has two nested loops. The inner loop handles the tool-call cycle. The outer loop exists to handle follow-up messages that arrive after the agent would otherwise stop.

```python
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

        # ... stream, execute tools, append results ...

    break  # no follow-up support in v1
```

`pending_messages` is the mechanism for extending a session with new user input mid-run. When a follow-up message is added to `pending_messages`, the inner loop picks it up at the start of the next iteration and merges it into `messages`.

In v1, the outer loop always breaks immediately — `pending_messages` is never populated because there is no async input handler. The structure is there for when steering support is added.

:::info
Pi.dev calls these "steering messages." They let a user redirect the agent mid-task without starting a new session. For example: "actually, skip the tests and just run the linter." The outer loop re-enters with the new instruction appended to the existing message history.
:::

## What a session is not

- **It is not persistent.** When `run_agent` exits, the session ends. The next call to `run_agent` starts fresh with a new `messages` list.
- **It is not shared.** Two concurrent `run_agent` calls have independent `messages` lists.
- **It is not recoverable.** If the process crashes mid-session, the conversation history is lost.

These are deliberate simplifications for v1.

## What persisting a session would require

If you wanted to save a session and resume it later, the approach is straightforward:

**Serialize** the `messages` list to JSON at the end of a run (or at checkpoints):

```python
import json

with open("session.json", "w") as f:
    json.dump(messages, f, indent=2)
```

**Deserialize** it to resume:

```python
with open("session.json") as f:
    messages = json.load(f)

# Append new task and continue
messages.append({"role": "user", "content": "Now add type hints too."})
await run_agent_from_messages(messages)
```

The `messages` list is plain JSON — dicts with string keys and string or list values. It serializes without any custom serialization logic.

:::note
Session persistence is not implemented in v1. The session format that would be used is described in [Session Format](../reference/session-format.md) (planned reference page).
:::

## Practical implications for v1

Because sessions are in-memory and per-run, every `run_agent` call is stateless from the perspective of prior runs. This means:

- The agent cannot remember a decision made in a previous session ("last time you told me to prefer `ruff` over `flake8`").
- If you want the agent to have context from a prior run, you must include that context in the initial task string or inject it via the `extra` parameter of `build_system_prompt()`.
- Long tasks that exceed `MAX_ITERATIONS = 30` cannot be resumed; they must be restarted with a more focused task.

For most learning and experimentation purposes, this is fine. The single-session, in-memory model is simple to reason about and easy to debug.

## Session lifetime at a glance

| Phase | What happens |
|---|---|
| `run_agent(task)` called | New `messages` list created with initial user message |
| Each inner iteration | Assistant + tool messages appended to `messages` |
| `pending_messages` flush | Follow-up messages merged into `messages` (v2 feature) |
| `finish_reason = "stop"` | Inner loop exits; outer loop checks for pending messages |
| Outer loop breaks | `run_agent` returns; `messages` goes out of scope and is garbage-collected |
| Next `run_agent` call | New session, no memory of the prior one |

## Related pages

- [The Context Window](./context-window.md) — how the messages list consumes tokens as it grows
- [Session Format](../reference/session-format.md) — planned specification for the serialized session JSON (not yet written)
- [Compaction](../advanced/compaction.md) — how to shrink a long session to avoid hitting the token limit
