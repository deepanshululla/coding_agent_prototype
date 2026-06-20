---
sidebar_position: 3
title: Phase 2 — The Conversation Loop
description: Build the while-loop skeleton in agent.py — messages as conversation state, the inner loop shape, and the text-only stop condition.
---

# Phase 2 — The Conversation Loop

:::note Starting point
Phase 1's `src/provider.py` — a `call_model` coroutine that returns the model's text. This phase wraps it in a loop.
:::

The agent is a loop. Not metaphorically — literally a `while True` with a break condition. This phase builds that loop in its simplest form: text in, text out, no tools yet.

## What you'll learn

How the `messages` list accumulates conversation state, why the loop structure matters even when there are no tools to call, and what "stop condition" means in a streaming context.

The key insight from pi.dev and the lecture that inspired this project: every agent framework — LangChain, LangGraph, AutoGPT — is an export of this loop. The loop is the agent. Building it yourself means you understand what you are using.

## Build it

Create `src/agent.py`. This phase's version is deliberately minimal: it calls the provider once, appends the assistant reply, and returns the history. The inner loop skeleton is present but exits after the first text reply.

```python
# src/agent.py
from __future__ import annotations

from provider import call_model

MAX_ITERATIONS = 30


async def run_agent(task: str) -> list[dict]:
    """Run the agent on task and return the final message history.

    Phase 2: text-only, no tools. The loop calls the model, appends the
    assistant reply, and stops when the model returns plain text (no tool
    calls to make).
    """
    messages: list[dict] = [{"role": "user", "content": task}]

    # OUTER LOOP: re-enters if follow-up messages arrive.
    # In this phase it runs exactly once.
    while True:
        has_more_tool_calls = True
        iteration = 0

        # INNER LOOP: the tool-call cycle.
        while has_more_tool_calls and iteration < MAX_ITERATIONS:
            iteration += 1

            # Phase A: ask the model
            reply_text = await call_model(
                messages=messages,
                system_prompt="You are a helpful coding assistant.",
            )

            # Phase B: append the assistant's reply to history
            messages.append({"role": "assistant", "content": reply_text})

            # Phase C: stop check — no tools in this phase, so a text reply
            # always means we are done.
            has_more_tool_calls = False

        break  # outer loop: no follow-up support yet

    return messages
```

### The messages list as state

`messages` is the entire conversation history. Every call to the model receives the full list — the model has no memory of its own. Each turn you append:

- The assistant's reply (Phase B above)
- Eventually: tool call results as `role: "tool"` messages (Phase 4)

The list grows with each iteration. That is how the model knows what has happened.

### The loop structure

The outer/inner split mirrors pi.dev's design. The outer loop handles follow-up messages that arrive after the agent would otherwise stop — called "steering" in pi's codebase. The inner loop is the actual tool-call cycle.

In this phase both loops are skeletal:
- The inner loop runs once and sets `has_more_tool_calls = False`.
- The outer loop runs once and `break`s.

The structure is there so that later phases can fill in the real logic without restructuring the code.

### The stop condition

`has_more_tool_calls = False` after a plain text reply is the Phase 2 stop condition. The logic is: if the model returned text and no tool calls were requested, there is nothing left to do. The inner loop exits, the outer loop breaks, and `run_agent` returns the history.

In Phase 4, this becomes: if `tool_calls` is empty after accumulating the stream, set `has_more_tool_calls = False`. Otherwise execute the tools and loop back. The condition is the same; only the detection of "what counts as a tool call" changes.

## Test it

Write the test first. Before writing any agent code, run this and confirm it fails.

```python
# tests/test_agent.py
import pytest


@pytest.mark.asyncio
async def test_run_agent_returns_user_and_assistant(monkeypatch):
    """The loop should seed messages with the user turn and append exactly
    one assistant reply when the model returns plain text."""
    import provider  # import the module so monkeypatch can target it

    async def fake_call_model(messages, system_prompt):
        return "Hi! How can I help?"

    monkeypatch.setattr(provider, "call_model", fake_call_model)

    from agent import run_agent

    history = await run_agent("say hi")

    assert len(history) == 2
    assert history[0] == {"role": "user", "content": "say hi"}
    assert history[1] == {"role": "assistant", "content": "Hi! How can I help?"}


@pytest.mark.asyncio
async def test_run_agent_stops_after_text_reply(monkeypatch):
    """The loop must stop after a single text reply — no further calls."""
    import provider

    call_count = 0

    async def counting_call_model(messages, system_prompt):
        nonlocal call_count
        call_count += 1
        return "Done."

    monkeypatch.setattr(provider, "call_model", counting_call_model)

    from agent import run_agent

    await run_agent("do something")

    assert call_count == 1, f"Expected 1 model call, got {call_count}"


@pytest.mark.asyncio
async def test_run_agent_passes_full_history_to_model(monkeypatch):
    """Each call to the model should receive the full message history so far."""
    import provider

    received_messages: list = []

    async def capturing_call_model(messages, system_prompt):
        received_messages.extend(messages)
        return "Response."

    monkeypatch.setattr(provider, "call_model", capturing_call_model)

    from agent import run_agent

    await run_agent("hello")

    # The model should have received the user message
    assert received_messages[0] == {"role": "user", "content": "hello"}
```

Run the tests before writing `agent.py`:

```bash
uv run pytest tests/test_agent.py -v
```

Expected (failing):

```
FAILED tests/test_agent.py::test_run_agent_returns_user_and_assistant - ModuleNotFoundError: No module named 'agent'
```

Now add `src/agent.py` with the code above. Run again:

```bash
uv run pytest tests/test_agent.py -v
```

Expected (passing):

```
tests/test_agent.py::test_run_agent_returns_user_and_assistant PASSED
tests/test_agent.py::test_run_agent_stops_after_text_reply PASSED
tests/test_agent.py::test_run_agent_passes_full_history_to_model PASSED

3 passed in 0.08s
```

:::tip
Notice that `monkeypatch.setattr(provider, "call_model", fake_call_model)` targets the `provider` module object, not `agent.call_model`. This is because `agent.py` imports `call_model` with `from provider import call_model`. To replace the function that `agent.py` actually calls, you patch it on the `provider` module — where the name `call_model` lives. If you patched `agent.call_model`, it would work too (and is slightly more direct), but patching the source module is the idiomatic approach.
:::

### Behavior (BDD)

Verify this phase as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Feature: The conversation loop
  run_agent seeds the message history with the user task, calls the model,
  appends the reply, and stops when the model returns plain text with no
  tool calls. The full history is passed to the model on every call.

  Scenario: A plain text reply produces exactly [user, assistant] and stops
    Given a scripted model that returns "Hi! How can I help?" with finish_reason "stop"
    When run_agent("say hi") completes
    Then the returned history has exactly 2 messages
    And messages[0] equals {"role": "user", "content": "say hi"}
    And messages[1] has role "assistant" and content "Hi! How can I help?"
    And no message in the history has role "tool"

  Scenario: The full prior history is sent on each model call
    Given a capturing model that records the messages it receives
    When run_agent("hello") completes
    Then the model received exactly one call
    And the messages list passed to the model contains the user message as its first element
    And the system_prompt argument is a non-empty string on every call

  Scenario: The loop makes exactly one model call for a no-tool task
    Given a counting model that increments a call counter and returns "Done."
    When run_agent("do something") completes
    Then the call counter is exactly 1
    And the loop did not re-enter after receiving the plain text reply
```

Run this as an integration scenario with the [BDD framework](../guides/bdd-integration-testing.md) — `pytest-bdd` over the `ScriptedLLM` harness from Phase 9. The unit test above proves the mechanism; this scenario specifies the *behavior*.

## Run it

Add a quick entry point to verify the loop works end-to-end against a real model:

```python
# scratch_phase2.py (repo root, throwaway)
import asyncio
import sys
import pathlib
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(pathlib.Path("src").resolve()))

from agent import run_agent

async def main():
    history = await run_agent("say hi in exactly four words")
    for msg in history:
        role = msg["role"].upper()
        content = msg.get("content", "")
        print(f"[{role}] {content}")

asyncio.run(main())
```

Run it:

```bash
uv run python scratch_phase2.py
```

Expected output (exact wording varies):

```
[USER] say hi in exactly four words
[ASSISTANT] Hello there, how are?
```

You ran `run_agent`, the loop called the model once, the model returned text, the loop stopped, and you printed the history. Two messages, one round-trip.

## Recap

You now have `src/agent.py` with a `run_agent(task)` coroutine. It seeds the message history with the user task, calls the model, appends the assistant reply, and returns the history. The outer/inner loop structure is in place even though it runs exactly once — the skeleton is ready for tool execution in Phase 4.

The stop condition is simple: no tool calls requested means the loop is done. That stays true in every phase; what changes is how "requested tool calls" are detected (from the streaming chunks in Phase 5).

**Go deeper:**
- [The Agent Loop](../architecture/the-agent-loop.md) — the full streaming loop with Phase A–E breakdown and parallel tool execution
