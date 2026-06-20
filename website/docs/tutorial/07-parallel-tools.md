---
sidebar_position: 8
title: Phase 7 — Parallel Tool Execution
description: Run multiple tool calls from a single model turn concurrently using asyncio.gather, and keep the loop responsive by wrapping blocking work in asyncio.to_thread.
---

# Phase 7 — Parallel Tool Execution

:::note Starting point
Phase 6's seven-tool registry, executed one tool at a time. This phase runs a turn's tools concurrently.
:::

When the model decides it needs multiple pieces of information at once it can request several tool calls in a single response turn. Executing them one after the other is wasteful — a `bash` call that takes two seconds doesn't need to block a `read_file` that would take five milliseconds. This phase adds `_execute_tools_parallel` and `_execute_one_tool` to `agent.py`, running all tool calls from a turn concurrently with `asyncio.gather`.

## What you'll learn

- How a single model turn can produce multiple tool calls and how they arrive in the stream.
- Why `asyncio.gather` is the right primitive for fan-out, and what it guarantees about result ordering.
- How unknown-tool errors are returned rather than raised — keeping the loop alive.
- Why the fallback `try/except` in `_execute_one_tool` exists even though tools promise never to raise.

## Build it

Add these two functions to `src/agent.py`, below `run_agent`:

```python
async def _execute_tools_parallel(tool_calls: list[dict]) -> list[ToolResult]:
    """Run every tool call concurrently and collect results in order."""
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
    except Exception as e:  # tools shouldn't raise, but never let one kill the loop
        return ToolResult(tool_call["id"], name, f"Error: {e}", is_error=True)
    print(f"  [✓ {name}: {len(result)} chars]")
    return ToolResult(tool_call["id"], name, result)
```

These functions are called from Phase D of the inner loop, which was already in place at the end of Phase 5:

```python
# ── Phase D: Execute tool calls in parallel ──────────────────────────────────
parsed_calls = [
    {
        "id": tc["id"],
        "name": tc["function"]["name"],
        "input": json.loads(tc["function"]["arguments"] or "{}"),
    }
    for tc in tool_calls
]
results = await _execute_tools_parallel(parsed_calls)
```

The full `agent.py` now looks like this:

```python
"""The agent: a nested outer/inner loop.

- The **inner loop** is the agent proper: stream a response, execute any requested tool
  calls in parallel, append the results, and go again — until the model returns text with
  no tool calls (``finish_reason == "stop"``).
- The **outer loop** re-enters only when follow-up ("steering") messages were queued after
  the agent would otherwise have stopped.

Streaming note: tool-call arguments arrive as **partial JSON strings** spread across
chunks. We buffer fragments by ``index`` and ``json.loads`` only once the stream ends.
"""

from __future__ import annotations

import asyncio
import json

from prompts import build_system_prompt
from provider import stream_response
from tools import TOOL_REGISTRY
from types_ import ToolResult

MAX_ITERATIONS = 30


async def run_agent(task: str) -> list[dict]:
    """Run the agent to completion on ``task``. Returns the final message history."""
    system_prompt = build_system_prompt()
    messages: list[dict] = [{"role": "user", "content": task}]
    pending_messages: list[dict] = []

    # OUTER LOOP: re-enter if follow-up messages arrive after the agent finishes.
    while True:
        has_more_tool_calls = True
        iteration = 0

        # INNER LOOP: the tool-call cycle.
        while (has_more_tool_calls or pending_messages) and iteration < MAX_ITERATIONS:
            iteration += 1

            if pending_messages:
                messages.extend(pending_messages)
                pending_messages.clear()

            # ── Phase A: Stream from the model ───────────────────────────────
            text_buf = ""
            tool_acc: dict[int, dict] = {}  # index → {id, name, arguments_buf}
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
                    slot = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments_buf": ""})
                    if tc_chunk.id:
                        slot["id"] = tc_chunk.id
                    fn = getattr(tc_chunk, "function", None)
                    if fn and fn.name:
                        slot["name"] = fn.name
                        print(f"\n▸ {fn.name}", end="", flush=True)
                    if fn and fn.arguments:
                        slot["arguments_buf"] += fn.arguments

            print()  # newline after the streamed turn

            # Finalize tool calls (arguments stay a JSON *string* in history).
            tool_calls = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments_buf"]},
                }
                for tc in tool_acc.values()
            ]

            # ── Phase B: Append the assistant turn to history ────────────────
            assistant_msg: dict = {"role": "assistant", "content": text_buf or None}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            # ── Phase C: Stop check ──────────────────────────────────────────
            if not tool_calls:
                has_more_tool_calls = False
                continue

            # ── Phase D: Execute tool calls in parallel ──────────────────────
            parsed_calls = [
                {
                    "id": tc["id"],
                    "name": tc["function"]["name"],
                    "input": json.loads(tc["function"]["arguments"] or "{}"),
                }
                for tc in tool_calls
            ]
            results = await _execute_tools_parallel(parsed_calls)

            # ── Phase E: Push tool results (one "tool" message each) ─────────
            for r in results:
                messages.append(
                    {"role": "tool", "tool_call_id": r.tool_call_id, "content": r.content}
                )

        break  # no follow-up source wired in v1; outer loop runs once

    return messages


async def _execute_tools_parallel(tool_calls: list[dict]) -> list[ToolResult]:
    """Run every tool call concurrently and collect results in order."""
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
    except Exception as e:  # tools shouldn't raise, but never let one kill the loop
        return ToolResult(tool_call["id"], name, f"Error: {e}", is_error=True)
    print(f"  [✓ {name}: {len(result)} chars]")
    return ToolResult(tool_call["id"], name, result)
```

### Design notes

**`asyncio.gather` preserves order.** Even though the coroutines run concurrently, `gather` returns a list that matches the input order. `results[0]` corresponds to `tool_calls[0]`, so tool result messages are appended to history in the same order the model requested them. Some providers are sensitive to ordering; this keeps things deterministic.

**Unknown-tool handling.** If `TOOL_REGISTRY.get(name)` returns `None`, the function builds a `ToolResult` with `is_error=True` immediately and returns — no exception, no crash. The model gets a message explaining what went wrong. This matters if you're experimenting with a model that hallucinates a tool name.

**The fallback `try/except`.** Tools promise never to raise (the cardinal contract from Phase 6). But promises can be broken — a bug in a new tool, a missing dependency, a malformed argument that bypasses the schema. The `try/except` is a last-resort backstop. It catches what the tool's own error handling missed and converts the exception into a `ToolResult` with `is_error=True`. The loop continues; the model sees the error and can try again.

**Why not `asyncio.to_thread` here?** `_execute_one_tool` is already `async` and each tool function is already `async` — the `asyncio.to_thread` wrapping for blocking I/O lives *inside* the tool functions (see Phase 6). `_execute_one_tool` just awaits the tool; `asyncio.gather` runs multiple awaitables concurrently.

## Test it

Write the test first, confirm it fails with an `AttributeError` or `ImportError` (because `_execute_tools_parallel` doesn't exist yet), then add the implementation.

Add this to `tests/test_agent.py`:

```python
"""Tests for parallel tool dispatch in the agent loop.

We test _execute_tools_parallel directly — no LLM call needed.
"""

import asyncio
import sys
from pathlib import Path

# src/ is not a package; make it importable.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import agent
from types_ import ToolResult


def run(coro):
    return asyncio.run(coro)


def test_parallel_dispatch_two_tools(tmp_path):
    """Two tool calls in one batch must both return results addressed to the right ids."""
    file_a = tmp_path / "a.txt"
    file_b = tmp_path / "b.txt"
    file_a.write_text("content of a")
    file_b.write_text("content of b")

    tool_calls = [
        {"id": "tc_001", "name": "read_file", "input": {"path": str(file_a)}},
        {"id": "tc_002", "name": "read_file", "input": {"path": str(file_b)}},
    ]

    results: list[ToolResult] = run(agent._execute_tools_parallel(tool_calls))

    assert len(results) == 2
    # Results come back in input order.
    assert results[0].tool_call_id == "tc_001"
    assert "content of a" in results[0].content
    assert results[1].tool_call_id == "tc_002"
    assert "content of b" in results[1].content
    # Neither should be an error.
    assert not results[0].is_error
    assert not results[1].is_error


def test_unknown_tool_returns_error_not_raise():
    """An unrecognised tool name must return is_error=True, not raise."""
    tool_calls = [
        {"id": "tc_bad", "name": "no_such_tool", "input": {}},
    ]
    results = run(agent._execute_tools_parallel(tool_calls))
    assert len(results) == 1
    assert results[0].is_error
    assert "Unknown tool" in results[0].content
```

Run:

```bash
uv run pytest tests/test_agent.py -v
```

Expected output:

```
tests/test_agent.py::test_parallel_dispatch_two_tools PASSED
tests/test_agent.py::test_unknown_tool_returns_error_not_raise PASSED
```

:::note
`test_parallel_dispatch_two_tools` submits two `read_file` calls for different files. Both coroutines start before either completes, so the total wall-clock time is bounded by the slower of the two — not the sum. For file reads the difference is negligible, but for `bash` calls that each take a second you would see the speedup clearly.
:::

### Behavior (BDD)

Verify this phase as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Feature: Parallel tool execution
  When the model emits multiple tool calls in a single streaming turn, the agent
  executes them concurrently and returns all results before the next model call.
  Order, error isolation, and unknown-name handling are all preserved.

  Scenario: two tool calls in one turn both return addressed to their correct ids
    Given files "a.txt" containing "content-alpha" and "b.txt" containing "content-beta"
    And a scripted model that requests read_file on both files in a single turn
    And the scripted model will then return a plain-text final answer
    When run_agent runs
    Then exactly 2 role:"tool" messages appear in the message history before the next assistant turn
    And the tool result with tool_call_id "c0" contains "content-alpha"
    And the tool result with tool_call_id "c1" contains "content-beta"

  Scenario: results preserve input order even if the slower tool was requested first
    Given files "slow.txt" and "fast.txt" exist
    And a scripted model that requests read_file on "slow.txt" at index 0 and read_file on "fast.txt" at index 1 in one turn
    And the scripted model will then return a plain-text final answer
    When run_agent runs
    Then the tool result messages appear in the history in request order: index-0 result before index-1 result

  Scenario: one tool erroring does not prevent the other tool's result from returning
    Given a scripted model that requests read_file on a missing path at index 0 and read_file on an existing "ok.txt" at index 1 in one turn
    And the scripted model will then return a plain-text final answer
    When run_agent runs
    Then the tool result for the missing path contains "Error"
    And the tool result for "ok.txt" contains the file's content
    And both role:"tool" messages are present (neither is missing due to the error)

  Scenario: an unknown tool name yields an error result not a crash
    Given a scripted model that requests an unknown tool "no_such_tool" in one turn
    And the scripted model will then return a plain-text final answer
    When run_agent runs
    Then the tool result message contains "Unknown tool"
    And run_agent completes without raising a Python exception
    And the final answer is the scripted plain-text response
```

Run this as an integration scenario with the [BDD framework](../guides/bdd-integration-testing.md) — `pytest-bdd` over the `ScriptedLLM` harness from Phase 9. The unit test above proves the mechanism; this scenario specifies the *behavior*.

## Run it

Give the agent a task that naturally triggers two reads in the same turn:

```bash
uv run main.py "Show me the first 5 lines of src/agent.py and the first 5 lines of src/tools.py"
```

Watch the output. If the model batches both reads into one turn you will see both `▸ read_file` markers appear before either `[executing ...]` line:

```
▸ read_file
▸ read_file
  [executing read_file {'path': 'src/agent.py', 'offset': 0, 'limit': 5}]
  [executing read_file {'path': 'src/tools.py', 'offset': 0, 'limit': 5}]
  [✓ read_file: 312 chars]
  [✓ read_file: 287 chars]

Here are the first five lines of each file: ...
```

If the model chooses to make two sequential turns instead, you'll see one `▸ read_file` per turn. Both are valid — the model decides; the loop handles either case correctly.

:::tip Architecture pattern
Reifying each tool call as a first-class object is the [Command](../architecture-patterns/command-pattern.md) pattern — it's what makes logging, replay, approvals, and undo possible once you outgrow plain function dispatch.
:::

## Recap

`_execute_tools_parallel` and `_execute_one_tool` are the only new code in this phase — thirty lines that turn sequential dispatch into concurrent fan-out. The key properties: `asyncio.gather` preserves order, unknown tools return `is_error=True` cleanly, and a fallback `try/except` ensures no tool can crash the loop.

For a deeper look at why `asyncio.gather` is the right primitive here — and how `asyncio.to_thread` interacts with it — see [concepts/async-and-concurrency.md](../concepts/async-and-concurrency.md). For the broader picture of how tool calls flow from the model through the loop and back, see [tools/parallel-execution.md](../tools/parallel-execution.md).

Next up: [Phase 8 — System Prompt & CLI](./08-system-prompt-and-cli.md), where you ground the agent with a dynamic system prompt and package the whole thing as a runnable CLI.
