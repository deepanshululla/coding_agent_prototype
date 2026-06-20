---
sidebar_position: 1
title: Using the Agent as a Library
description: Import run_agent() from agent.py and drive it from your own async Python code instead of the CLI.
---

# Using the Agent as a Library

`main.py` is a thin CLI wrapper. The real entry point is `run_agent(task)` in `src/agent.py`. You can import and call it directly from any async Python program.

:::note
`src/agent.py` is planned but not yet implemented. The interface described here reflects the design in `PLAN.md`. Once implemented, this page will serve as the integration reference.
:::

## What `run_agent` does

```python
async def run_agent(task: str) -> None:
    ...
```

It takes a task string, builds the system prompt, initialises the message history, and runs the outer/inner loop until the model signals `finish_reason == "stop"` with no outstanding tool calls. In v1 it returns `None` — all output goes to stdout via `print()`.

## How `main.py` wraps it

```python
# main.py
import asyncio
import sys
from dotenv import load_dotenv
from agent import run_agent

async def main():
    load_dotenv()
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Task: ")
    await run_agent(task)

if __name__ == "__main__":
    asyncio.run(main())
```

That's the entire CLI. No argument parsing, no config file loading, no output routing — just `asyncio.run` over `run_agent`. If you want to drive the agent from a test, a script, or another service, you replicate that pattern.

## Calling `run_agent` from your own code

### From a standalone script

```python
import asyncio
import os
from dotenv import load_dotenv

# Add src/ to the path if you're running from the repo root
import sys
sys.path.insert(0, "src")

from agent import run_agent

async def main():
    load_dotenv()
    await run_agent("List all Python files and summarise what each one does.")

asyncio.run(main())
```

Run it:

```bash
uv run my_script.py
```

### From an existing async application

If your application already runs an event loop, `await` directly — don't nest `asyncio.run` calls:

```python
async def handle_user_request(user_input: str):
    # run_agent streams to stdout; in v1 you observe output there
    await run_agent(user_input)
```

### From a test

The cleanest way to test the agent loop itself is to mock `stream_response` so no real API call is made. See `tests/test_agent.py` for the pattern:

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

# A canned chunk that looks like a "stop" turn with no tool calls
STOP_CHUNK = ...  # build a mock ModelResponse

@patch("agent.stream_response", return_value=async_generator([STOP_CHUNK]))
async def test_run_agent_no_tools(mock_stream):
    await run_agent("hello")
    mock_stream.assert_called_once()
```

See [the agent loop](../architecture/the-agent-loop.md) for a full explanation of what the mock needs to produce.

## Capturing output instead of printing it

In v1, `run_agent` streams text and tool status directly to stdout via `print(..., flush=True)`. There is no return value and no callback hook yet.

To capture output in a parent script, redirect stdout:

```python
import io
import contextlib

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    await run_agent("What files are in the current directory?")

captured = buf.getvalue()
```

This works but is coarse — you get all interleaved text and tool-status lines together. For structured capture (text vs. tool events vs. results as separate streams), the planned [JSON Event Stream mode](./json-event-stream.md) is the right approach.

## Return values — v1 vs. future

| Version | Return value | Capture method |
|---------|-------------|----------------|
| v1 (current design) | `None` | `redirect_stdout` or subprocess |
| Planned | `AgentResult` (final text + tool history) | Await and inspect |
| Planned (streaming) | `AsyncIterator[AgentEvent]` | `async for event in run_agent(...)` |

The current `None` return is deliberate: it keeps the loop simple while the design stabilises. Structured return values and event callbacks are extension points described in [JSON Event Stream mode](./json-event-stream.md).

## Path setup

`src/` is not a package — there is no `__init__.py`. You have two options:

**Option A — `sys.path` at runtime** (shown above): add `"src"` to `sys.path` before importing.

**Option B — `pyproject.toml`** (recommended for tests):

```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
```

This makes `src/` importable in all `pytest` runs without touching `sys.path` in application code.

## Related pages

- [The Agent Loop](../architecture/the-agent-loop.md) — inner/outer loop mechanics
- [RPC Mode](./rpc-mode.md) — exposing `run_agent` over HTTP or stdin/stdout JSON-RPC
- [JSON Event Stream Mode](./json-event-stream.md) — structured event output for programmatic consumers
