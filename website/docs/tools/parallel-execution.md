---
sidebar_position: 4
title: Parallel Execution
description: How the agent runs multiple tool calls concurrently using asyncio.gather, and why this matters.
---

# Parallel Execution

When the model requests multiple tools in a single turn, the agent runs them all at the same time. This mirrors the design of pi.dev, where parallel tool execution is the default — not an optimisation bolt-on.

## Why it matters

Consider a model that wants to read three files before deciding how to proceed. Sequential execution waits for each file read to complete before starting the next. Parallel execution fires all three simultaneously and waits for all of them to finish. For I/O-bound tools (file reads, subprocess calls), the wall-clock time is roughly the same as a single tool call, not three times as long.

For a coding agent making dozens of tool calls per task, the cumulative difference is significant.

## How it works

The agent loop collects all tool calls from a single model turn, then passes them together to `_execute_tools_parallel`:

```python
# src/agent.py

async def _execute_tools_parallel(tool_calls: list[dict]) -> list[ToolResult]:
    tasks = [_execute_one_tool(tc) for tc in tool_calls]
    return await asyncio.gather(*tasks)
```

`asyncio.gather` schedules all tasks concurrently and returns a list of results in the **same order** as the input list. This ordering is guaranteed — even though tasks finish in unpredictable order, `gather` collects them by position.

Each individual tool call runs through `_execute_one_tool`:

```python
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

:::note
The code shown here matches the shipped `src/agent.py`.
:::

## Async tools and `asyncio.to_thread`

All tool functions are declared as `async def`. This lets the event loop schedule them cooperatively. However, most tool operations — reading files, running subprocesses — are inherently blocking. A naive `async def` that calls `Path.read_text()` directly would block the event loop thread during the I/O, preventing other tools from making progress.

The fix is `asyncio.to_thread`, which offloads a blocking call to a thread pool and `await`s its completion:

```python
# Inside a tool implementation
async def read_file(path: str, offset: int = 0, limit: int = 2000) -> str:
    def _read():
        text = Path(path).read_text()
        lines = text.splitlines()
        return "\n".join(lines[offset : offset + limit])

    return await asyncio.to_thread(_read)
```

With `asyncio.to_thread`, the blocking work runs in a thread while the event loop remains free to start other tool tasks. The result is true concurrency for I/O-bound tools.

For tools that shell out via `subprocess.run`, wrap the call the same way:

```python
async def bash(command: str) -> str:
    def _run():
        result = subprocess.run(
            command, shell=True, capture_output=True, timeout=30, text=True
        )
        output = (result.stdout + result.stderr)[:10_000]
        return f"{output}\nexit_code: {result.returncode}"

    return await asyncio.to_thread(_run)
```

## Result collection and ordering

After `asyncio.gather` returns, results are in the same order as the `tool_calls` list that went in. The loop appends each result to the message history as a separate `role: "tool"` message, in that order:

```python
for r in results:
    messages.append({
        "role": "tool",
        "tool_call_id": r.tool_call_id,
        "content": r.content,
    })
```

Each result is matched back to its tool call via `tool_call_id`. The model correlates these IDs when it reads the results.

## One failure doesn't stop the others

Because each task is independent inside `asyncio.gather`, a failure in one tool (caught as an exception inside `_execute_one_tool`) does not cancel the others. Every task runs to completion; errors are returned as `ToolResult` objects with `is_error=True`, not as exceptions that would propagate out of `gather`.

This is the right behaviour for a coding agent: if two of three concurrent tool calls succeed, the model should see all three results — including which one failed and why — so it can reason and recover.

## Related pages

- [Overview](./overview.md) — how the loop phases work end-to-end
- [Error Handling](./error-handling.md) — how individual tool failures are contained
- [Built-in Tools](./built-in-tools.md) — the 7 tools that execute in parallel
