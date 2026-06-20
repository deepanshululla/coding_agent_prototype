---
sidebar_position: 4
title: Phase 3 — Streaming Responses
description: Switch the `claude -p` backend to `--output-format stream-json`, translate its events into OpenAI-format chunks, and accumulate text deltas as they arrive.
---

# Phase 3 — Streaming Responses

:::note Implemented
This step is implemented on branch `step/phase-03-streaming` (plan: `plans/tutorial/phase-03-streaming.md`).
:::

:::note Starting point
Phase 2's text-only `run_agent` loop, calling `call_model`. This phase converts that call to streaming and renames the function `stream_response`.
:::

In Phases 1–2 the provider was `call_model`, a coroutine that returned one finished string. This phase **renames it to `stream_response` and turns it into an async generator**, so tokens arrive incrementally. You print each delta as it lands and track `finish_reason` so the agent loop knows when the model is done talking.

The backend is still `claude -p` — but now with `--output-format stream-json` instead of `text`. The CLI emits newline-delimited JSON events that this phase translates into the same OpenAI-format chunk shape that the agent loop (and all later phases) depend on.

:::note
LiteLLM will replace this backend in [Phase 11](./11-add-litellm.md). When it does, `stream_response` will yield the exact same chunk shape — the agent loop does not change at all. The class encapsulates the swap.
:::

## What you'll learn

How to consume `claude -p --output-format stream-json` events from a subprocess, how to translate them into OpenAI-format chunks using `SimpleNamespace`, and how to accumulate `text_buf` and `finish_reason` in the agent loop. The chunk shape you build here — `.choices[0].delta.content`, `.delta.tool_calls`, `.finish_reason` — is what every later phase depends on.

## Build it

All changes are in `src/provider.py`. Add a streaming path to `ModelClient`, add a helper `_chunk()` to build OpenAI-format chunks from the CLI's JSON events, and expose the module-level `stream_response` async generator.

```python
# src/provider.py
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

MODEL_ALIAS = "sonnet"   # passed to claude --model


def _chunk(content=None, finish_reason=None):
    """Build one OpenAI-format streaming chunk the agent loop understands."""
    delta = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


class ModelClient:
    """Wraps `claude -p` as a streaming completion backend."""

    async def complete(self, messages: list[dict], system_prompt: str) -> str:
        """Non-streaming path (kept for reference; loop uses stream() from Phase 3 on)."""
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

    async def stream(
        self, messages: list[dict], system_prompt: str
    ) -> AsyncIterator[Any]:
        """Stream via `claude -p --output-format stream-json`.

        Translates CLI events into OpenAI-format chunks so the agent loop
        sees the same interface regardless of backend.
        """
        prompt = messages[-1]["content"]
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", prompt,
            "--system-prompt", system_prompt,
            "--model", MODEL_ALIAS,
            "--output-format", "stream-json",
            "--verbose",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        async for raw_line in proc.stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            # stream-json emits assistant events with text blocks.
            if event.get("type") == "assistant":
                for block in event["message"]["content"]:
                    if block.get("type") == "text":
                        yield _chunk(content=block["text"])
            elif event.get("type") == "result":
                yield _chunk(finish_reason="stop")
        await proc.wait()


# Module singleton.
_client = ModelClient()


async def call_model(messages: list[dict], system_prompt: str) -> str:
    """Non-streaming call — kept so Phase 1/2 code still works."""
    return await _client.complete(messages, system_prompt)


async def stream_response(
    messages: list[dict], system_prompt: str
) -> AsyncIterator[Any]:
    """Stream a model response as OpenAI-format chunks.

    This is the function the agent loop imports from Phase 3 onward. The
    underlying backend (claude -p now; LiteLLM in Phase 11) is hidden behind
    ModelClient — the signature and chunk shape never change.
    """
    async for chunk in _client.stream(messages, system_prompt):
        yield chunk
```

The accumulation and printing happen in `src/agent.py`, inside the inner loop:

```python
# src/agent.py  — Phase A of the inner loop
text_buf = ""
tool_acc: dict[int, dict] = {}
finish_reason = None

async for chunk in stream_response(messages, system_prompt):
    choice = chunk.choices[0]
    delta = choice.delta
    finish_reason = choice.finish_reason or finish_reason   # carry it forward

    if getattr(delta, "content", None):
        text_buf += delta.content
        print(delta.content, end="", flush=True)            # live output
```

Two things worth noting:

- `choice.finish_reason or finish_reason` — most chunks have `finish_reason=None`; the final chunk sets it. The `or` idiom keeps the last non-None value without an `if`.
- `print(..., end="", flush=True)` — `end=""` suppresses the default newline so tokens stitch together visually; `flush=True` forces the OS buffer to emit immediately.

After the `async for` completes, print a newline:

```python
print()  # newline after the streamed turn
```

### Chunk shape contract

The `_chunk()` helper produces the shape every later phase relies on:

| Attribute | Type | Set when |
|---|---|---|
| `.choices[0].delta.content` | `str \| None` | Text token arrives |
| `.choices[0].delta.tool_calls` | `list \| None` | Tool-call fragment (Phase 4+) |
| `.choices[0].finish_reason` | `str \| None` | `"stop"` or `"tool_calls"` on the last chunk |

Phases 4–10 do not touch `ModelClient` — they only read this shape. Phase 11 swaps the class body; the shape stays identical.

## Test it

Write the failing test first. The test feeds canned chunks through `ScriptedLLM` (already in `tests/test_agent.py`) and asserts that the accumulated content is correct.

```python
# tests/test_agent.py  — add this test

def test_streaming_text_accumulates(monkeypatch):
    """Text fragments from multiple chunks are joined into one assistant message."""
    turns = [
        [
            _chunk(content="one"),
            _chunk(content=", "),
            _chunk(content="two"),
            _chunk(content=", "),
            _chunk(content="three"),
            _chunk(finish_reason="stop"),
        ]
    ]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))

    messages = asyncio.run(agent.run_agent("count to three"))

    assistant = messages[1]
    assert assistant["role"] == "assistant"
    assert assistant["content"] == "one, two, three"
    assert "tool_calls" not in assistant
```

Confirm the test fails before you add the streaming accumulation code, then make it pass:

```bash
uv run pytest tests/test_agent.py::test_streaming_text_accumulates -v
```

Expected output after the fix:

```
tests/test_agent.py::test_streaming_text_accumulates PASSED
```

:::tip No CLI yet?
The `ScriptedLLM` in the test file lets you exercise the accumulation loop without any subprocess call. The `test_streaming_text_accumulates` test above is a complete verification of the logic in isolation — the CLI is only needed when you run the real script below.
:::

### Behavior (BDD)

Verify this phase as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Feature: Streaming accumulation
  stream_response yields OpenAI-format chunks; run_agent accumulates content
  fragments into a single assistant message and carries finish_reason forward
  from the one chunk that sets it. An empty stream must still terminate cleanly.

  Scenario: Multiple text fragments are joined into one assistant message
    Given a scripted model that yields chunks with content "one", ", ", "two", ", ", "three"
    And a final chunk with finish_reason "stop"
    When run_agent("count to three") completes
    Then messages[1] has role "assistant"
    And messages[1]["content"] equals "one, two, three"
    And "tool_calls" is not present in messages[1]

  Scenario: finish_reason is carried forward from the single chunk that sets it
    Given a scripted model that yields five content chunks all with finish_reason None
    And then a final empty chunk with finish_reason "stop"
    When run_agent processes the stream
    Then the accumulated finish_reason after the loop is "stop"
    And the assistant message content is the concatenation of all five content strings
    And the loop exits cleanly without reading past the finish chunk

  Scenario: An empty stream with no content chunks still terminates without error
    Given a scripted model that yields only a single chunk with finish_reason "stop" and no content
    When run_agent("say nothing") completes
    Then no exception is raised
    And the returned history has exactly 2 messages
    And messages[1] has role "assistant"
    And messages[1]["content"] is None or an empty string
```

Run this as an integration scenario with the [BDD framework](../guides/bdd-integration-testing.md) — `pytest-bdd` over the `ScriptedLLM` harness from Phase 9. The unit test above proves the mechanism; this scenario specifies the *behavior*.

## Run it

With the `claude` CLI logged in, ask the agent something that produces a multi-token reply:

```bash
uv run main.py "count to five slowly"
```

You should see tokens appear as they arrive:

```
one... two... three... four... five.
```

Each token prints as it lands rather than the entire response appearing all at once. That is the visible proof that streaming is working.

## Recap

Switching to `stream-json` output turns a single subprocess call into an event stream. Each `assistant` event from the CLI maps to one or more `_chunk(content=...)` calls; the final `result` event maps to `_chunk(finish_reason="stop")`. The agent loop reads `.choices[0].delta.content` and `.finish_reason` — the same shape it will read from LiteLLM in Phase 11.

The important design rule: `stream_response` is the only name the loop imports. The class and the `_chunk` helper are implementation details. Phase 11 replaces them without changing a single line outside `provider.py`.

For a deeper look at the chunk shape, how tool-call fragments differ from text fragments, and how the accumulation buffer works, see [Streaming and Events](../architecture/streaming-and-events.md).
