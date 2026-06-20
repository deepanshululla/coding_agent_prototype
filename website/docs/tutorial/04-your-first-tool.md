---
sidebar_position: 5
title: Phase 4 — Your First Tool
description: Define a tool schema, let the model request it, execute it, and feed the result back as a role:tool message so the model can continue.
---

# Phase 4 — Your First Tool

:::note Implemented
This step is implemented on branch `step/phase-04-your-first-tool` (plan: `plans/tutorial/phase-04-your-first-tool.md`).
:::

:::note Starting point
Phase 3's streaming `run_agent` — it accumulates text deltas but has no tools yet. This phase gives the model its first tool.
:::

:::warning Tool-calling through `claude -p` is a simplified bridge
The `claude -p` backend used through Phase 10 is itself an agent harness — it runs its own loop with its own built-in tools. It does **not** accept this project's `TOOLS_SCHEMA` so that *our* loop can drive *our* seven tools through the native function-calling protocol. The tool dispatch in this phase works because `ScriptedLLM` (in tests) and the loop logic are independent of the backend; in a live run the CLI backend handles text turns only.

The robust, multi-provider function-calling path — where the model actually receives `TOOLS_SCHEMA` and emits structured `tool_calls` deltas — arrives with LiteLLM in [Phase 11](./11-add-litellm.md). See [Claude CLI Backend](../customization/claude-cli-backend.md) for the full options and the tool-call translation strategy.
:::

The streaming loop from Phase 3 only handles text. This phase adds the tool-calling cycle: you define one tool (`read_file`), tell the model it exists, detect when the model requests it, run it, and push the result back as a `role:"tool"` message so the model can use the output.

By the end of this phase the agent can read a file and summarize it — without you writing the logic to decide which file to read.

## What you'll learn

The OpenAI-style tool call protocol, end to end:

1. **Schema** — a JSON object describing the tool's name, description, and parameters, passed to the model as `tools=`.
2. **Detection** — when the model wants a tool it sets `finish_reason="tool_calls"` and populates `delta.tool_calls` in the stream.
3. **Dispatch** — look up the function by name in `TOOL_REGISTRY`, call it with the parsed arguments.
4. **Result injection** — append the assistant turn (which contains `tool_calls`) *and* a `{"role": "tool", ...}` message for each result, then loop again.

This phase treats each tool call's arguments as arriving in a single chunk (no partial JSON yet). Streaming tool-call argument accumulation is Phase 5.

## Build it

### 1. Add `read_file` and its schema to `src/tools.py`

```python
# src/tools.py
from __future__ import annotations

import asyncio
from pathlib import Path


async def read_file(path: str, offset: int = 0, limit: int = 2000) -> str:
    """Read a file, optionally a window of limit lines starting at offset."""

    def _read() -> str:
        try:
            lines = Path(path).read_text().splitlines()
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except IsADirectoryError:
            return f"Error: {path} is a directory, not a file"
        except Exception as e:
            return f"Error reading {path}: {e}"
        window = lines[offset : offset + limit]
        return "\n".join(window)

    return await asyncio.to_thread(_read)


TOOLS_SCHEMA: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file. Use offset/limit for large files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to read",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Line to start from (0-indexed)",
                        "default": 0,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max lines to return",
                        "default": 2000,
                    },
                },
                "required": ["path"],
            },
        },
    },
]

TOOL_REGISTRY: dict[str, object] = {
    "read_file": read_file,
}
```

Three things to notice:
- The schema uses `"parameters"` (not `"input_schema"`). LiteLLM expects OpenAI format and translates to whatever the underlying provider needs.
- The function is `async def` and wraps blocking file I/O in `asyncio.to_thread` — so it does not stall the event loop when parallel tools are added later.
- On failure it returns an error *string*, never raises. The model reads the error and can try something else.

### 2. Pass the schema to the model in `src/provider.py`

`provider.py` already imports `TOOLS_SCHEMA` and passes `tools=TOOLS_SCHEMA` to `acompletion` — that part is already in place from Phase 3. No changes needed here if you followed that phase.

### 3. Detect tool calls and dispatch in `src/agent.py`

Add `types_.py` first:

```python
# src/types_.py
from dataclasses import dataclass


@dataclass
class ToolResult:
    tool_call_id: str
    tool_name: str
    content: str
    is_error: bool = False
```

Then extend the inner loop in `src/agent.py`:

```python
# src/agent.py
import asyncio
import json

from prompts import build_system_prompt
from provider import stream_response
from tools import TOOL_REGISTRY
from types_ import ToolResult

MAX_ITERATIONS = 30


async def run_agent(task: str) -> list[dict]:
    system_prompt = build_system_prompt()
    messages: list[dict] = [{"role": "user", "content": task}]

    while True:
        has_more_tool_calls = True
        iteration = 0

        while has_more_tool_calls and iteration < MAX_ITERATIONS:
            iteration += 1

            # ── Phase A: Stream ──────────────────────────────────────────────
            text_buf = ""
            tool_acc: dict[int, dict] = {}
            finish_reason = None

            async for chunk in stream_response(messages, system_prompt):
                choice = chunk.choices[0]
                delta = choice.delta
                finish_reason = choice.finish_reason or finish_reason

                if getattr(delta, "content", None):
                    text_buf += delta.content
                    print(delta.content, end="", flush=True)

                for tc_chunk in getattr(delta, "tool_calls", None) or []:
                    idx = tc_chunk.index
                    slot = tool_acc.setdefault(
                        idx, {"id": "", "name": "", "arguments_buf": ""}
                    )
                    if tc_chunk.id:
                        slot["id"] = tc_chunk.id
                    fn = getattr(tc_chunk, "function", None)
                    if fn and fn.name:
                        slot["name"] = fn.name
                        print(f"\n▸ {fn.name}", end="", flush=True)
                    if fn and fn.arguments:
                        slot["arguments_buf"] += fn.arguments

            print()

            # Finalize tool calls (arguments stay a JSON string in history).
            tool_calls = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments_buf"],
                    },
                }
                for tc in tool_acc.values()
            ]

            # ── Phase B: Append assistant turn ───────────────────────────────
            assistant_msg: dict = {"role": "assistant", "content": text_buf or None}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            # ── Phase C: Stop check ──────────────────────────────────────────
            if not tool_calls:
                has_more_tool_calls = False
                continue

            # ── Phase D: Execute tool calls ──────────────────────────────────
            parsed_calls = [
                {
                    "id": tc["id"],
                    "name": tc["function"]["name"],
                    "input": json.loads(tc["function"]["arguments"] or "{}"),
                }
                for tc in tool_calls
            ]
            results = await _execute_tools_parallel(parsed_calls)

            # ── Phase E: Push tool results ───────────────────────────────────
            for r in results:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": r.tool_call_id,
                        "content": r.content,
                    }
                )

        break

    return messages


async def _execute_tools_parallel(tool_calls: list[dict]) -> list[ToolResult]:
    return await asyncio.gather(*(_execute_one_tool(tc) for tc in tool_calls))


async def _execute_one_tool(tool_call: dict) -> ToolResult:
    name = tool_call["name"]
    args = tool_call["input"]
    print(f"  [executing {name} {args}]")
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
    try:
        result = await fn(**args)
    except Exception as e:
        return ToolResult(tool_call["id"], name, f"Error: {e}", is_error=True)
    print(f"  [✓ {name}: {len(result)} chars]")
    return ToolResult(tool_call["id"], name, result)
```

Key protocol details:

- The assistant turn that requests a tool **must** carry `tool_calls` in message history, even if `content` is empty. Omitting it breaks the provider's conversation validation.
- Each tool result is its own message with `role="tool"` and a `tool_call_id` that matches the call. OpenAI format — not packed into a `role:"user"` block.
- `arguments` stays a JSON *string* in the message history. Parse it with `json.loads` only when dispatching. Providers re-send it back verbatim; converting to a dict corrupts that round-trip.

:::warning One tool call at a time — for now
This phase assumes each tool call's arguments arrive in a single chunk. That is true in non-streaming mode but not guaranteed when streaming. Phase 5 fixes this by accumulating `arguments_buf` fragments and parsing only after the stream ends.
:::

## Test it

Write the failing test first. The scripted model turn 1 requests `read_file` with full arguments in one chunk; turn 2 returns text and stops.

```python
# tests/test_agent.py  — add this test

def test_tool_call_then_stop(monkeypatch, tmp_path):
    """A read_file call executes and its content lands in a role:tool message."""
    target = tmp_path / "hello.txt"
    target.write_text("hello from the file")

    # Turn 1: model requests read_file with complete arguments.
    turn1 = [
        _chunk(
            tool_calls=[
                _tc(
                    0,
                    id="call_abc",
                    name="read_file",
                    arguments=f'{{"path": "{target}"}}',
                )
            ],
        ),
        _chunk(finish_reason="tool_calls"),
    ]
    # Turn 2: model summarizes and stops.
    turn2 = [
        _chunk(content="The file says: hello from the file."),
        _chunk(finish_reason="stop"),
    ]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM([turn1, turn2]))

    messages = asyncio.run(agent.run_agent("read hello.txt"))

    # Assistant turn 1 carries the tool_calls field.
    assistant1 = messages[1]
    assert assistant1["role"] == "assistant"
    assert assistant1["tool_calls"][0]["function"]["name"] == "read_file"
    # arguments stay as a JSON string, not a dict.
    assert isinstance(assistant1["tool_calls"][0]["function"]["arguments"], str)

    # A role:tool message follows with the file content.
    tool_msg = messages[2]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "call_abc"
    assert "hello from the file" in tool_msg["content"]

    # Final turn: model's summary.
    assert messages[-1]["content"] == "The file says: hello from the file."
```

Run it:

```bash
uv run pytest tests/test_agent.py::test_tool_call_then_stop -v
```

Expected output after the implementation is in place:

```
tests/test_agent.py::test_tool_call_then_stop PASSED
```

### Behavior (BDD)

Verify this phase as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Feature: First tool call
  When the model emits finish_reason "tool_calls", run_agent executes the named
  tool, injects the result as a role:"tool" message addressed to the matching
  tool_call_id, and loops back to the model. The assistant turn that carries
  the tool call is appended to history before any tool result messages.

  Scenario: The model calls read_file and the file contents return as a role:"tool" message
    Given a file "notes.txt" containing "meeting at 3pm"
    And a scripted model whose turn 1 requests read_file on notes.txt with finish_reason "tool_calls"
    And turn 2 replies "The note says: meeting at 3pm." with finish_reason "stop"
    When run_agent("what's in notes.txt?") completes
    Then the history contains a role:"tool" message before the second assistant turn
    And that tool message content includes "meeting at 3pm"
    And the final assistant message content is "The note says: meeting at 3pm."

  Scenario: The assistant turn carrying a tool call has arguments as a JSON string, not a dict
    Given a scripted model that requests read_file with arguments '{"path": "/tmp/x.txt"}'
    And a follow-up turn that stops
    When run_agent completes
    Then messages[1] has role "assistant" and a "tool_calls" key
    And messages[1]["tool_calls"][0]["function"]["arguments"] is an instance of str
    And json.loads of that string succeeds and contains the key "path"

  Scenario: The tool result message is addressed to the correct tool_call_id
    Given a scripted model that requests read_file with id "call_abc" and finish_reason "tool_calls"
    And a follow-up turn that stops
    When run_agent completes
    Then the role:"tool" message in history has tool_call_id equal to "call_abc"
    And no other tool_call_id appears in the tool messages

  Scenario: A read of a missing file returns an error result and the loop continues
    Given no file exists at the path the scripted model will request
    And a scripted model whose turn 1 requests read_file on that missing path
    And turn 2 replies "The file does not exist; I cannot proceed." with finish_reason "stop"
    When run_agent("read missing.txt") completes
    Then the role:"tool" message content contains "error" or "not found" (case-insensitive)
    And the loop did not crash or raise an exception
    And the history contains exactly 2 assistant turns (the tool-call turn and the recovery turn)
```

Run this as an integration scenario with the [BDD framework](../guides/bdd-integration-testing.md) — `pytest-bdd` over the `ScriptedLLM` harness from Phase 9. The unit test above proves the mechanism; this scenario specifies the *behavior*.

## Run it

With a real API key in `.env`, ask the agent to read a file in the project:

```bash
uv run main.py "read src/tools.py and tell me what tools are defined"
```

You should see something like:

```
▸ read_file
  [executing read_file {'path': 'src/tools.py'}]
  [✓ read_file: 4312 chars]

The file defines seven tools: read_file, write_file, edit_file, bash, grep, find_files,
and list_dir. Each tool has an async implementation and an entry in TOOLS_SCHEMA and
TOOL_REGISTRY.
```

The model chose the file path, issued the tool call, received the content, and summarized it — all without you directing any of that.

## Recap

A tool is three wired-together pieces: an async function, an OpenAI-style schema dict in `TOOLS_SCHEMA`, and an entry in `TOOL_REGISTRY`. The model decides when to use a tool; the loop detects `finish_reason="tool_calls"`, parses the arguments, calls the function, and injects the result as a `role:"tool"` message before looping again. The critical protocol invariant: append the assistant turn *with its `tool_calls` field* before appending any tool results, and keep `arguments` as a JSON string in history.

For the full list of tools and their schemas, see [Tools Overview](../tools/overview.md) and [Schema Format](../tools/schema-format.md).
