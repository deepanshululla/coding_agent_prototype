---
sidebar_position: 12
title: Phase 11 — Add LiteLLM (Multi-Provider)
description: Swap ModelClient's body from `claude -p` to `litellm.acompletion` — one model string picks the provider, the loop doesn't change at all.
---

# Phase 11 — Add LiteLLM (Multi-Provider)

:::note Implemented
This step is implemented on branch `step/phase-11-add-litellm` (plan: `plans/tutorial/phase-11-add-litellm.md`).
:::

:::note Starting point
The finished agent from Phase 9 (or 10), whose model backend is the `claude -p` wrapper in `src/provider.py`. The agent loop, tools, and tests all depend on `stream_response(messages, system_prompt)` yielding OpenAI-format chunks — that interface does not change in this phase.
:::

The `claude -p` backend has been a useful training wheel: no API key, no SDK, works with your existing Claude login. But it has a ceiling:

- It is **Claude-only** — you cannot swap to Gemini or GPT-4o by changing a string.
- It is **an agent harness, not a clean model API** — `claude -p` runs its own loop with its own tools and does not natively accept this project's `TOOLS_SCHEMA` for structured function-calling.
- The stream-json translation layer you wrote in Phase 3 is custom code that each new provider would need duplicated.

LiteLLM fixes all three: it normalizes every provider to the OpenAI chunk format, routes to the right provider based on the model string prefix, and picks up the matching API key from the environment automatically. Swap `"claude-sonnet-4-5"` for `"gemini/gemini-2.0-flash"` or `"gpt-4o"` — that is the entire provider change.

## What you'll learn

Why LiteLLM is the right convergence point, how to swap only `ModelClient`'s body without touching anything the loop imports, and how the repo simplifies to the final `src/provider.py` form once the class is no longer needed as an abstraction boundary.

## Build it

### Step 1 — Install LiteLLM

```bash
uv add litellm
```

### Step 2 — Swap `ModelClient`'s body

Only `src/provider.py` changes. The function name `stream_response`, its parameters, and its chunk-yield contract are all preserved. The agent loop, `src/agent.py`, `src/tools.py`, `src/prompts.py`, and all tests remain untouched.

```python
# src/provider.py  — Phase 11: LiteLLM backend
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import litellm

from tools import TOOLS_SCHEMA

MODEL = "claude-sonnet-4-5"   # prefix selects provider; change to swap
MAX_TOKENS = 8096


class ModelClient:
    """LiteLLM-backed streaming completion client."""

    async def stream(
        self, messages: list[dict], system_prompt: str
    ) -> AsyncIterator[Any]:
        """Stream via litellm.acompletion with tool support.

        Yields OpenAI-format chunks unchanged — the same shape the loop
        has consumed since Phase 3.
        """
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        response = await litellm.acompletion(
            model=MODEL,
            messages=full_messages,
            tools=TOOLS_SCHEMA,
            tool_choice="auto",
            max_tokens=MAX_TOKENS,
            stream=True,
        )
        async for chunk in response:
            yield chunk


_client = ModelClient()


async def stream_response(
    messages: list[dict], system_prompt: str
) -> AsyncIterator[Any]:
    """Stream a model response as OpenAI-format chunks.

    This signature has not changed since Phase 3. The backend has.
    """
    async for chunk in _client.stream(messages, system_prompt):
        yield chunk
```

Compare with the Phase 3 version: the class body swaps from subprocess+JSON-parsing to `litellm.acompletion(..., stream=True)`. `stream_response` is byte-for-byte identical in signature.

### Step 3 — Simplify to the final form

With LiteLLM as the only backend, the class is no longer pulling its weight as an abstraction boundary — it wraps one function call. The shipped `src/provider.py` in this repo collapses it:

```python
# src/provider.py  — final shipped form
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import litellm

from tools import TOOLS_SCHEMA

MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 8096


async def stream_response(
    messages: list[dict], system_prompt: str
) -> AsyncIterator[Any]:
    """Stream a model response as OpenAI-format chunks.

    acompletion is non-blocking, so the event loop stays free to execute tools
    concurrently while tokens arrive. Yields chunks unchanged for the agent loop
    to accumulate.
    """
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    response = await litellm.acompletion(
        model=MODEL,
        messages=full_messages,
        tools=TOOLS_SCHEMA,
        tool_choice="auto",
        max_tokens=MAX_TOKENS,
        stream=True,
    )
    async for chunk in response:
        yield chunk
```

This is exactly what lives in `src/provider.py` today. `MODEL`, `MAX_TOKENS`, and `stream_response` — nothing else. The class existed to make the swap teachable; once the swap is done it is dead code.

### Set a provider API key

LiteLLM reads standard per-provider environment variables. Add one to `.env` at the repo root:

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...      # for claude-* models
# OPENAI_API_KEY=sk-...           # for gpt-* models
# GEMINI_API_KEY=...              # for gemini/* models
```

```python
# main.py — already loads .env at startup
from dotenv import load_dotenv
load_dotenv()
```

LiteLLM picks up the key from `os.environ` automatically — no client construction needed.

### Swap the model string to change providers

| Model string | Provider | Key needed |
|---|---|---|
| `"claude-sonnet-4-5"` | Anthropic | `ANTHROPIC_API_KEY` |
| `"gpt-4o"` | OpenAI | `OPENAI_API_KEY` |
| `"gemini/gemini-2.0-flash"` | Google | `GEMINI_API_KEY` |
| `"groq/llama-3-8b-8192"` | Groq | `GROQ_API_KEY` |

Change the `MODEL` constant in `src/provider.py`. That is the entire provider switch.

## Test it

The existing test suite exercises `stream_response` through monkeypatching `agent.stream_response` — it has never called the real backend. So **the loop tests already pass with the LiteLLM backend**. Run the full suite to confirm:

```bash
uv run pytest tests/test_agent.py -v
```

Expected output:

```
tests/test_agent.py::test_plain_text_turn_stops PASSED
tests/test_agent.py::test_tool_call_then_stop PASSED
tests/test_agent.py::test_multiple_parallel_tool_calls PASSED
tests/test_agent.py::test_unknown_tool_is_reported_not_raised PASSED

4 passed in 0.XX s
```

The interface is stable. The backend changed; the tests did not.

You can also add a test that asserts `stream_response` is an async generator (i.e., the signature contract holds):

```python
# tests/test_provider.py
import inspect
import provider


def test_stream_response_is_async_generator():
    """stream_response must be an async generator function — the loop depends on it."""
    assert inspect.isasyncgenfunction(provider.stream_response)
```

```bash
uv run pytest tests/test_provider.py::test_stream_response_is_async_generator -v
```

Expected output:

```
tests/test_provider.py::test_stream_response_is_async_generator PASSED
```

### Behavior (BDD)

Verify this phase as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Feature: Backend swap invariance
  Replacing the claude -p subprocess with litellm.acompletion behind the same
  stream_response signature leaves the loop, tools, and tests entirely unchanged.

  Scenario: the existing loop scenarios pass unchanged after swapping to LiteLLM
    Given src/provider.py is updated to call litellm.acompletion instead of claude -p
    And agent.stream_response is monkeypatched with ScriptedLLM as in every other test
    When the full tests/test_agent.py suite runs
    Then all 4 loop tests pass without modification
    And no test imports litellm directly (the backend is hidden behind stream_response)

  Scenario: stream_response stays an async generator yielding the same chunk shape
    Given the LiteLLM-backed src/provider.py is in place
    When inspect.isasyncgenfunction(provider.stream_response) is evaluated
    Then the result is True
    And each chunk yielded has the attribute path chunk.choices[0].delta.content or chunk.choices[0].delta.tool_calls
    And each chunk yielded has the attribute chunk.choices[0].finish_reason

  Scenario: changing the MODEL string routes to a different provider with no loop change
    Given MODEL in src/provider.py is set to "gpt-4o"
    And agent.stream_response is monkeypatched so no real network call is made
    When run_agent is called and the ScriptedLLM produces a plain-text answer
    Then run_agent completes successfully
    And src/agent.py, src/tools.py, and src/prompts.py are identical to their Phase 9 versions (no edits required)

  Scenario: tools schema is passed through to litellm.acompletion
    Given the LiteLLM-backed provider is in place
    And litellm.acompletion is monkeypatched to capture its keyword arguments
    When stream_response is called with a messages list and a system prompt
    Then litellm.acompletion is called with tools=TOOLS_SCHEMA
    And litellm.acompletion is called with tool_choice="auto"
    And litellm.acompletion is called with stream=True
```

Run this as an integration scenario with the [BDD framework](../guides/bdd-integration-testing.md) — `pytest-bdd` over the `ScriptedLLM` harness from Phase 9. The unit test above proves the mechanism; this scenario specifies the *behavior*.

## Run it

With `ANTHROPIC_API_KEY` in `.env`:

```bash
uv run main.py "list all .py files in src/"
```

To try a different provider, update `MODEL` in `src/provider.py` and set the matching key:

```bash
# src/provider.py
MODEL = "gpt-4o"   # or "gemini/gemini-2.0-flash"
```

```bash
# .env
OPENAI_API_KEY=sk-...
```

```bash
uv run main.py "list all .py files in src/"
```

The agent's behavior is identical — the same tools, the same loop, the same output format. Only the model behind it changed.

:::tip Architecture pattern
Swapping the backend behind a stable `stream_response` is the [Ports & Adapters](../architecture-patterns/ports-and-adapters.md) pattern in action: `stream_response` is the `LLMPort`, and `claude -p` and LiteLLM are two interchangeable adapters.
:::

## Recap

Phase 11 is a single-file change: `ModelClient.stream` swaps from `asyncio.create_subprocess_exec("claude", ...)` to `litellm.acompletion(..., stream=True)`. The class then collapses because it was only ever the swap point. What remains is `MODEL`, `MAX_TOKENS`, and `stream_response` — a 20-line file.

The design rule that made this painless: `stream_response` was the only name the loop imported since Phase 3. The class and the subprocess were always implementation details. Hiding them behind a stable function signature meant Phase 11 was a backend swap, not a refactor.

**Go deeper:**
- [The Provider Layer](../architecture/provider-layer.md) — the streaming implementation and async model
- [Custom Providers](../customization/custom-providers.md) — how to add non-LiteLLM backends
- [Claude CLI Backend](../customization/claude-cli-backend.md) — bringing `claude -p` back as an opt-in toggle
- [Providers & Models](../getting-started/providers-and-models.md) — full model string reference and API key setup

Next: [Phase 12 — Harden It](./12-harden-it/1-security-model.md) — make the agent safe to run: security model, command allowlist, permission modes, sandboxing, and logging.
