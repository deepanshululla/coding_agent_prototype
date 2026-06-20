---
sidebar_position: 2
title: Phase 1 — Talk to a Model
description: Build a ModelClient wrapper around the Claude CLI (`claude -p`) and expose a call_model function — no API key required.
---

# Phase 1 — Talk to a Model

:::note Implemented
This step is implemented on branch `step/phase-01-talk-to-a-model` (plan: `plans/tutorial/phase-01-talk-to-a-model.md`).
:::

:::note Starting point
An empty project — `uv` initialized, no dependencies yet. The only requirement is the `claude` CLI on your PATH and a completed login (`claude` once interactively, or `claude setup-token`). No `ANTHROPIC_API_KEY` needed for this phase.
:::

Before the agent loop, before tools, before streaming — there is one thing: sending a message to a model and getting text back. That is what this phase builds.

The twist: instead of hitting the model API directly, this phase shells out to the [Claude Code CLI](https://docs.claude.com/en/docs/claude-code) with `claude -p` (print mode). You already have it installed if you are using Claude Code. It carries your existing login, so the agent runs with zero per-token API billing and no key to manage during development.

LiteLLM — the real multi-provider backend — arrives in [Phase 11](./11-add-litellm.md). Streaming arrives in [Phase 3](./03-streaming.md). The CLI entry point is [Phase 8](./08-system-prompt-and-cli.md).

## What you'll learn

How to subprocess `claude -p` from Python with `asyncio.create_subprocess_exec`, how to capture stdout, and how to wrap that in a `ModelClient` class and a stable module-level function that the rest of the tutorial calls. You will also learn why the function sits behind a class — it makes the backend swappable in Phase 11 without touching any code that calls it.

## Build it

Create `src/provider.py`. The class `ModelClient` owns the subprocess logic. A module singleton exposes a plain function `call_model` that the agent loop imports. Nothing outside `provider.py` needs to know a class exists.

```python
# src/provider.py
from __future__ import annotations

import asyncio

MODEL_ALIAS = "sonnet"   # passed to claude --model; change to "opus" etc.


class ModelClient:
    """Wraps `claude -p` to make a single non-streaming completion call."""

    async def complete(self, messages: list[dict], system_prompt: str) -> str:
        """Run claude -p with the latest user message and return the reply text."""
        prompt = messages[-1]["content"]
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", prompt,
            "--system-prompt", system_prompt,
            "--model", MODEL_ALIAS,
            "--output-format", "text",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode().strip()


# Module singleton — everything outside provider.py imports this function only.
_client = ModelClient()


async def call_model(messages: list[dict], system_prompt: str) -> str:
    """Send messages to the model and return the reply text.

    Delegates to the ModelClient singleton. Callers never instantiate the class.
    Phase 3 renames this to stream_response and makes it an async generator.
    Phase 11 swaps the class body to LiteLLM without changing this signature.
    """
    return await _client.complete(messages, system_prompt)
```

That is the entire file for this phase. No API client, no authentication setup, no response parsing — just stdout from a subprocess.

### Why a class?

The class is the seam. The function `call_model` (and later `stream_response`) is the stable interface everything else imports. When Phase 11 switches the backend to LiteLLM, only `ModelClient`'s body changes. The agent loop, the tests, the tool dispatch — none of them change.

### Why `asyncio.create_subprocess_exec`?

The subprocess call is I/O-bound and can take seconds. Using `asyncio.create_subprocess_exec` keeps the event loop free during that wait instead of blocking the thread. Even in Phase 1 — before there is anything else to do concurrently — it is better to establish the async pattern the rest of the tutorial builds on.

### The `claude -p` flags used here

`--output-format text` makes the CLI return just the assistant text on stdout, with no metadata. `--model sonnet` picks the model alias. `--system-prompt` injects a system prompt without you having to format a message history. See [Claude CLI Backend](../customization/claude-cli-backend.md) for the full flag reference, including `stream-json` (used in Phase 3) and the tool-calling caveat.

:::note
Phase 11 adds `ANTHROPIC_API_KEY` (or another provider's key) and switches the class body to `litellm.acompletion`. Until then, the CLI carries your auth and `call_model` is the only interface you expose.
:::

## Test it

Write this test first, before touching `provider.py`. Run it and confirm it fails with a `ModuleNotFoundError` or `NameError`, not a passing result.

The test monkeypatches the `_run` helper on `ModelClient` so no real subprocess fires.

```python
# tests/test_provider.py
import asyncio
import pytest
import provider


@pytest.mark.asyncio
async def test_call_model_returns_text(monkeypatch):
    """call_model should return the text content from the model's reply."""

    async def fake_complete(self, messages, system_prompt):
        return "Hello from the model!"

    monkeypatch.setattr(provider.ModelClient, "complete", fake_complete)

    result = await provider.call_model(
        messages=[{"role": "user", "content": "say hi"}],
        system_prompt="You are a helpful assistant.",
    )

    assert result == "Hello from the model!"


@pytest.mark.asyncio
async def test_call_model_passes_latest_message(monkeypatch):
    """ModelClient.complete receives the messages list intact."""
    captured: dict = {}

    async def capturing_complete(self, messages, system_prompt):
        captured["messages"] = messages
        captured["system_prompt"] = system_prompt
        return "ok"

    monkeypatch.setattr(provider.ModelClient, "complete", capturing_complete)

    await provider.call_model(
        messages=[{"role": "user", "content": "hello"}],
        system_prompt="You are a test assistant.",
    )

    assert captured["messages"][-1] == {"role": "user", "content": "hello"}
    assert captured["system_prompt"] == "You are a test assistant."
```

Install `pytest-asyncio` if you don't have it yet:

```bash
uv add --dev pytest pytest-asyncio
```

Add this to `pyproject.toml` so `pytest-asyncio` runs async tests automatically:

```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
asyncio_mode = "auto"
```

Run the tests (before writing `provider.py`, expect a `ModuleNotFoundError`):

```bash
uv run pytest tests/test_provider.py -v
```

Expected output before the implementation:

```
FAILED tests/test_provider.py::test_call_model_returns_text - ModuleNotFoundError: No module named 'provider'
```

Now add `src/provider.py` with the code above and run again:

```bash
uv run pytest tests/test_provider.py -v
```

Expected output:

```
tests/test_provider.py::test_call_model_returns_text PASSED
tests/test_provider.py::test_call_model_passes_latest_message PASSED

2 passed in 0.08s
```

:::tip
Monkeypatching `ModelClient.complete` is the right pattern here — you replace the class method, not the subprocess call itself. The test proves the delegation chain (function → singleton → class method) without spawning any process.
:::

### Behavior (BDD)

Verify this phase as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Feature: Talking to the model
  call_model sends a message to the model backend and returns the reply text.
  The function is the stable interface for all later phases; the class and
  subprocess details are implementation details hidden behind it.

  Scenario: A user message returns the model's text reply
    Given a mocked ModelClient.complete that returns "hi there"
    When call_model is invoked with messages=[{"role":"user","content":"say hi"}]
    And system_prompt is "You are a helpful assistant."
    Then the return value is exactly "hi there"
    And no subprocess is spawned during the call

  Scenario: The system prompt is forwarded to the backend intact
    Given a capturing ModelClient.complete that records its arguments
    When call_model is invoked with any user message and system_prompt "Be brief."
    Then the captured system_prompt equals "Be brief."
    And the captured messages list ends with the user message that was passed in

  Scenario: An empty string reply from the model does not raise
    Given a mocked ModelClient.complete that returns ""
    When call_model is invoked with a user message
    Then the return value is "" and no exception is raised
    And the caller receives an empty string it can check before displaying
```

Run this as an integration scenario with the [BDD framework](../guides/bdd-integration-testing.md) — `pytest-bdd` over the `ScriptedLLM` harness from Phase 9. The unit test above proves the mechanism; this scenario specifies the *behavior*.

## Run it

With `src/provider.py` in place and the `claude` CLI logged in, create a minimal script:

```python
# scratch_phase1.py (at the repo root, not in src/)
import asyncio
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path("src").resolve()))

from provider import call_model

async def main():
    reply = await call_model(
        messages=[{"role": "user", "content": "say hi in exactly five words"}],
        system_prompt="You are a concise assistant.",
    )
    print(reply)

asyncio.run(main())
```

Run it:

```bash
uv run python scratch_phase1.py
```

Expected output (exact wording varies):

```
Hello there, how are you?
```

The round-trip works: `call_model` shelled out to `claude -p`, captured stdout, and returned it. That is Phase 1 complete.

:::note
`scratch_phase1.py` is a throwaway verification script. Do not commit it. The test suite in `tests/test_provider.py` is the lasting artifact.
:::

## Recap

You now have `src/provider.py` with a `ModelClient` class and a module-level function `call_model` that delegates to a singleton. The class shells out to `claude -p --output-format text` and returns stdout. No API key, no SDK imports — just your existing Claude login.

Two things the class design gives you now:

1. The function signature `call_model(messages, system_prompt) -> str` is stable. Everything that calls it in Phases 2 and 3 does not care how it is implemented.
2. When Phase 11 swaps the class body to LiteLLM, the function signature stays identical — zero changes outside `provider.py`.

**Go deeper:**
- [Claude CLI Backend](../customization/claude-cli-backend.md) — the full `claude -p` flag reference and the tool-calling caveat
- [The Provider Layer](../architecture/provider-layer.md) — the full streaming implementation and why async matters
- [Providers & Models](../getting-started/providers-and-models.md) — model string reference and provider swap instructions
