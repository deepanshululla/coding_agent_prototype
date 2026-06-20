---
sidebar_position: 4
title: Your First Task
description: Walk through a realistic agent task end to end — what the agent reads, edits, and verifies, and what each line of output means.
---

# Your First Task

This page walks through one real task from start to finish: adding type hints to `tools.py`. You'll see every tool call the agent makes, why it makes them, and what the streamed output means at each step.

:::note
`src/tools.py` is implemented. The walkthrough below describes real behavior you will see when you run the agent.
:::

## The task

```bash
uv run main.py "add type hints to tools.py"
```

This is a good first task because it involves reading code, making targeted edits, and verifying the result — all three of the agent's core abilities.

## Phase 1: Exploration

The agent doesn't modify files immediately. It reads first.

```
I'll start by reading tools.py to understand the current function signatures.
▸ read_file
  [executing read_file {'path': 'src/tools.py'}]
  [✓ read_file: 2847 chars]
```

The `▸ read_file` marker appears the moment the model emits that tool call in the stream — before the tool has even executed. The `[executing ...]` and `[✓ ...]` lines print during and after execution.

The agent now has the full file in its context. It identifies which functions lack type annotations.

## Phase 2: Edits

The agent uses `edit_file` rather than `write_file` for targeted changes. `edit_file` finds an exact string in the file and replaces it. This is intentional: replacing the whole file would lose any changes made concurrently and is harder to review.

If multiple functions need type hints and they're independent of each other, the agent may call `edit_file` several times in the same turn:

```
I'll add type hints to each function. Starting with read_file and bash, then the rest.
▸ edit_file
▸ edit_file
  [executing edit_file {'path': 'src/tools.py', 'old_string': 'async def read_file(path, offset=0, limit=2000):', 'new_string': 'async def read_file(path: str, offset: int = 0, limit: int = 2000) -> str:'}]
  [executing edit_file {'path': 'src/tools.py', 'old_string': 'async def bash(command):', 'new_string': 'async def bash(command: str) -> str:'}]
  [✓ edit_file: 18 chars]
  [✓ edit_file: 18 chars]
```

Both `▸ edit_file` markers appear at nearly the same time because the model emitted both tool calls in a single turn. The loop collects all tool calls from the stream, then executes them in parallel via `asyncio.gather`. The `[✓ ...]` lines may arrive in any order.

:::tip
Parallel tool execution is one of the design wins from pi.dev. If the agent needs to read three files, all three `read_file` calls happen concurrently rather than sequentially.
:::

The agent continues with the remaining functions — likely in another turn or two, each with batched edits.

## Phase 3: Verification

After all edits, the agent does not simply declare success. It runs a syntax check and the test suite:

```
Now I'll verify the edits with a syntax check and run the tests.
▸ bash
  [executing bash {'command': 'uv run python -m py_compile src/tools.py && echo "syntax OK"'}]
  [✓ bash: 11 chars]

▸ bash
  [executing bash {'command': 'uv run pytest tests/test_tools.py -q'}]
  [executing bash ...]
  [✓ bash: 412 chars]

All 7 tool tests pass. The type hints are in place and the module compiles cleanly.
```

The `bash` tool runs the command in a subprocess, captures stdout and stderr, and returns both along with the exit code. If `pytest` reports failures, the agent sees the failure output in the tool result and may attempt a fix — or explain what it found and stop.

## What you see in the stream, decoded

| Output line | What it means |
|---|---|
| Plain text prose | The model is explaining its reasoning before, between, or after tool calls |
| `▸ tool_name` | The model just emitted this tool call in the current chunk; execution hasn't started yet |
| `[executing tool_name {...}]` | The loop is running the tool; parallel calls print here simultaneously |
| `[✓ tool_name: N chars]` | The tool returned successfully; N is the length of its output |
| `[executing tool_name ...]` (without full args) | Very long args are truncated for display |

If a tool fails, the loop marks the result `is_error=True` and returns a descriptive error string. The model sees that error, reasons about it, and decides what to do next — it does not crash.

## Why the agent stops

The inner loop exits when the model produces a turn with `finish_reason: "stop"` and no tool calls. At that point, the agent has decided it's done. The outer loop then checks for any queued follow-up messages; finding none (v1 doesn't support mid-run input), it breaks.

The `MAX_ITERATIONS = 30` cap is the safety valve. It prevents an agent that keeps calling tools indefinitely from running forever.

## Next steps

- [The Agent Loop](../architecture/the-agent-loop.md) — the full inner/outer loop mechanics, streaming accumulation, and parallel execution in detail
- [Configuration](./configuration.md) — tune `MAX_ITERATIONS` and `max_tokens`
