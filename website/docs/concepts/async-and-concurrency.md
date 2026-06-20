---
sidebar_position: 3
title: Async & Concurrency
description: Why the agent is fully async, how asyncio.gather enables parallel tool execution, and how asyncio.to_thread keeps blocking I/O from stalling the event loop.
---

# Async & Concurrency

The entire agent is `async` — from `run_agent()` down through every tool function. This is not a style preference. It follows directly from the two things the agent spends most of its time doing: waiting for streamed tokens from the model, and running multiple tools simultaneously.

:::note
`src/agent.py`, `src/provider.py`, and `src/tools.py` are implemented. The behavior described below reflects the shipped code.
:::

## Why sync completion blocks

Consider the synchronous alternative:

```python
# Sync — DO NOT use
response = litellm.completion(model=MODEL, messages=messages, stream=True)
for chunk in response:
    process(chunk)
```

While `litellm.completion` is waiting for the first token from the network, the Python thread is blocked. Nothing else can run. If you wanted to execute two tools concurrently, you would need threads — with all the complexity of thread safety, locking, and GIL contention.

The async version avoids this entirely:

```python
# Async — what the agent uses
response = await litellm.acompletion(model=MODEL, messages=messages, stream=True)
async for chunk in response:
    process(chunk)
```

`litellm.acompletion` is non-blocking. While it waits for the network, the event loop is free to run other coroutines. This is the foundation that makes parallel tool execution possible without threads.

## The event loop mental model

Python's `asyncio` event loop is a single-threaded scheduler. It runs one coroutine at a time, but it can switch between coroutines at every `await` point.

```
Event loop tick
│
├── run_agent() is awaiting acompletion → suspended
│   event loop picks up next ready coroutine
│
├── (if tools are running) tool_A() is awaiting asyncio.to_thread → suspended
│   tool_B() resumes and does CPU work
│   tool_A() I/O completes → scheduled again
│
└── acompletion yields a chunk → run_agent() resumes, processes chunk
```

The key insight: `await` is a yield point. Every time your code hits `await`, control returns to the event loop, which finds something else to run. Long-running operations that never `await` block the loop for everyone.

## asyncio.gather for parallel tool batches

When the model returns multiple tool calls in a single turn, the agent executes them all at once:

```python
async def _execute_tools_parallel(tool_calls: list[dict]) -> list[ToolResult]:
    tasks = [_execute_one_tool(tc) for tc in tool_calls]
    return await asyncio.gather(*tasks)
```

`asyncio.gather` schedules all coroutines as concurrent tasks and waits for all of them to complete. The total wall-clock time is approximately the duration of the slowest tool, not the sum.

For example, if the model calls `read_file`, `grep`, and `bash` simultaneously:

```
Without gather (sequential):   read_file(200ms) + grep(300ms) + bash(500ms) = 1000ms
With gather (concurrent):      max(200ms, 300ms, 500ms) ≈ 500ms
```

This matters for real coding tasks. Running tests, grepping a codebase, and reading a config file concurrently cuts latency significantly compared to sequential execution.

## asyncio.to_thread for blocking I/O inside tools

The tools themselves use blocking operations: `subprocess.run` for shell commands, `Path.read_text()` for file reads. These are not async — they block the OS thread until they complete.

Calling them directly inside an `async def` tool would block the event loop:

```python
# Wrong — blocks the event loop
async def bash(cmd: str) -> str:
    result = subprocess.run(cmd, shell=True, capture_output=True, timeout=30)
    return result.stdout.decode()
```

The fix is `asyncio.to_thread`, which runs the blocking call in a thread-pool thread and returns an awaitable:

```python
# Correct — releases the event loop while subprocess runs
async def bash(cmd: str) -> str:
    def _run():
        result = subprocess.run(cmd, shell=True, capture_output=True, timeout=30)
        return result.stdout.decode()
    return await asyncio.to_thread(_run)
```

While the subprocess is running in the thread pool, the event loop is free — other tool coroutines can make progress, and new chunks from the model stream can be processed.

The same pattern applies to file I/O:

```python
async def read_file(path: str, offset: int = 0, limit: int = 2000) -> str:
    def _read():
        lines = Path(path).read_text().splitlines()
        return "\n".join(lines[offset:offset + limit])
    return await asyncio.to_thread(_read)
```

## How it all fits together

Here is the concurrency picture for a single inner-loop iteration where the model requests two tools:

```
run_agent() (coroutine)
│
├── await stream_response(messages, system_prompt)
│     ├── await litellm.acompletion(...)   ← suspends; event loop free
│     └── async for chunk in response:     ← resumes on each chunk
│           accumulate text_buf, tool_acc
│
├── await _execute_tools_parallel([tool_A, tool_B])
│     ├── asyncio.gather schedules both
│     │
│     ├── _execute_one_tool(tool_A)
│     │     └── await asyncio.to_thread(subprocess.run, ...)   ← thread pool
│     │
│     └── _execute_one_tool(tool_B)
│           └── await asyncio.to_thread(Path.read_text, ...)   ← thread pool
│
│     (both run concurrently; gather returns when both finish)
│
└── append results to messages; loop continues
```

## Summary

| Mechanism | What it solves |
|---|---|
| `litellm.acompletion` | Non-blocking model call; event loop stays free during token streaming |
| `asyncio.gather` | Runs all tool calls in a batch concurrently; total time = slowest tool |
| `asyncio.to_thread` | Offloads blocking subprocess/file I/O to a thread pool without blocking the event loop |
| `async def` tools | Allows `await` inside tools so they participate in cooperative scheduling |

The combination means the agent is I/O-bound in the most efficient way Python allows: it waits on multiple things simultaneously without needing explicit threads or callbacks.
