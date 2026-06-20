---
sidebar_position: 6
title: "Logging"
description: How the agent uses loguru to route diagnostics to stderr and keep stdout clean for the model's output.
---

# Logging

The recommended logging approach is [loguru](https://github.com/Delgan/loguru) for diagnostic
output, with two channels — stdout and stderr — kept deliberately separate, wired up by a single
`setup_logging()` call in `main.py`.

:::note Status
This is a **supported design**, not yet wired into the shipped core. Today `agent.py` prints its
diagnostic lines (`[executing …]`, `[✓ …]`) to stdout alongside the model output. This page
specifies the loguru setup that moves diagnostics onto stderr and adds levels + a file sink — a
small, self-contained change (`src/logging_config.py` + swapping the `print`s for `logger` calls).
:::

## Two channels, one design decision

The agent routes output along two separate paths:

| Channel | Carries | Mechanism |
|---|---|---|
| **stdout** | The model's streamed text; `▸ tool` call markers | `print()` in `agent.py` |
| **stderr** | Diagnostics: tool lifecycle, errors, iteration counts | loguru `logger` |

This split is intentional. With stdout clean, you can pipe the agent's result to another
command without log noise leaking in. You can also crank up log verbosity to `DEBUG` while
the model writes to its own stream, and neither channel interferes with the other.

```bash
# Capture only the agent's output — logs go to the terminal on stderr.
uv run main.py "summarize README.md" > result.txt

# Or suppress stderr entirely to see just the result.
uv run main.py "summarize README.md" 2>/dev/null
```

:::tip
If you are building a tool that consumes the agent's output programmatically, always redirect
or discard stderr. Parsing stdout is stable; the stderr format is for humans.
:::

## Setup

`main.py` calls `setup_logging()` once at startup, after `load_dotenv()`:

```python
async def main() -> None:
    load_dotenv()
    setup_logging()  # reads AGENT_LOG_LEVEL from env; default INFO
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Task: ")
    await run_agent(task)
```

`setup_logging()` is idempotent — calling it more than once is safe and has no effect after
the first call. You never need to call it yourself when using the CLI. If you embed the agent
as a library, call it once early in your process.

## Environment variables

Two env vars control logging behaviour. Both are read inside `setup_logging()`.

| Variable | Default | Effect |
|---|---|---|
| `AGENT_LOG_LEVEL` | `INFO` | Minimum severity sent to stderr (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `AGENT_LOG_FILE` | _(unset)_ | Path for a rotating JSON file sink; omit to disable |

Add either or both to your `.env`:

```bash
# .env
AGENT_LOG_LEVEL=DEBUG
AGENT_LOG_FILE=/tmp/agent.log
```

Or export them directly:

```bash
AGENT_LOG_LEVEL=DEBUG uv run main.py "find all TODO comments"
```

See [Settings Reference](./settings.md) for the full list of `AGENT_*` env vars.

### File sink details

When `AGENT_LOG_FILE` is set, a second loguru sink opens alongside stderr:

- **Rotation:** the file rolls over at 10 MB.
- **Retention:** 5 rotated files are kept; older ones are deleted automatically.
- **Format:** `serialize=True` writes one JSON object per log record — suitable for ingestion
  into a log aggregator. See [Structured logs](#structured-logs-for-ingestion) below.

## stderr format

The stderr sink uses a human-readable, coloured format:

```
HH:mm:ss | LEVEL   | module - message
```

Example at INFO:

```
14:23:01 | INFO    | agent - agent starting: 'fix the type error in tools.py'
14:23:04 | INFO    | agent - agent finished after 3 iteration(s)
```

## What gets logged

All log calls live in `src/agent.py`. Here is the complete inventory:

| Event | Level | Message pattern |
|---|---|---|
| Agent starts | `INFO` | `agent starting: {!r}` (task string) |
| Each iteration | `DEBUG` | `iteration {N}/{MAX_ITERATIONS}` |
| Tool about to execute | `DEBUG` | `executing tool {name} with {args}` |
| Tool completed | `DEBUG` | `tool {name} ok: {N} chars` |
| Unknown tool requested | `WARNING` | `unknown tool requested: {name}` |
| Tool raised an exception | `ERROR` + traceback | `tool {name} raised` |
| Loop hit max iterations | `WARNING` | `hit MAX_ITERATIONS ({N}); stopping with work possibly unfinished` |
| Agent finishes | `INFO` | `agent finished after {N} iteration(s)` |

### Sample stderr transcript — INFO level

At the default `INFO` level you see the agent's lifetime and any warnings:

```
14:23:01 | INFO    | agent - agent starting: 'add docstrings to all functions in tools.py'
14:23:09 | INFO    | agent - agent finished after 4 iteration(s)
```

### Sample stderr transcript — DEBUG level

At `DEBUG` you see every iteration and every tool call:

```
14:23:01 | DEBUG   | logging_config - logging configured at level DEBUG
14:23:01 | INFO    | agent - agent starting: 'add docstrings to all functions in tools.py'
14:23:01 | DEBUG   | agent - iteration 1/30
14:23:03 | DEBUG   | agent - executing tool read_file with {'path': 'src/tools.py'}
14:23:03 | DEBUG   | agent - tool read_file ok: 4821 chars
14:23:03 | DEBUG   | agent - iteration 2/30
14:23:05 | DEBUG   | agent - executing tool write_file with {'path': 'src/tools.py', 'content': '...'}
14:23:05 | DEBUG   | agent - tool write_file ok: 23 chars
14:23:06 | DEBUG   | agent - iteration 3/30
14:23:08 | INFO    | agent - agent finished after 3 iteration(s)
```

:::note
The `▸ tool_name` markers you see printed in the terminal come from `print()` calls on stdout,
not from the logger. They are part of the user-facing output stream, not diagnostics.
:::

## Using the logger in your own tools or extensions

Import the shared logger from `logging_config` — do not create your own loguru logger:

```python
from logging_config import logger

async def my_custom_tool(path: str) -> str:
    logger.debug("my_custom_tool called with path={}", path)
    # ... do work ...
    logger.info("my_custom_tool finished: {} bytes written", bytes_written)
    return result
```

loguru uses brace-style (`{}`) formatting, not `%`-style. Arguments are lazily interpolated,
so building an f-string yourself wastes work:

```python
# Good — loguru formats this only if the level is active.
logger.debug("executing tool {} with {}", name, args)

# Avoid — the f-string is always evaluated, even at INFO level.
logger.debug(f"executing tool {name} with {args}")
```

Use the right level:

- `logger.debug(...)` — high-frequency, per-call detail (tool execution, iteration counts).
- `logger.info(...)` — coarse lifecycle events (agent start/finish, major phase changes).
- `logger.warning(...)` — recoverable unexpected conditions (unknown tool, max-iteration hit).
- `logger.error(...)` — failures that affect correctness but don't crash the process.
- `logger.exception(...)` — same as `error` but automatically attaches the current traceback.
  Use this inside `except` blocks (as `agent.py` does for tool exceptions).

## Structured logs for ingestion

When `AGENT_LOG_FILE` points to a path, every log record is serialized as a JSON object on
its own line. Each line contains the timestamp, level, module, function, line number, and the
rendered message:

```json
{
  "text": "14:23:01 | INFO    | agent - agent starting: 'fix the type error'\n",
  "record": {
    "elapsed": {"repr": "0:00:00.012345", "seconds": 0.012345},
    "exception": null,
    "extra": {},
    "file": {"name": "agent.py", "path": "/path/to/src/agent.py"},
    "function": "run_agent",
    "level": {"icon": "ℹ️", "name": "INFO", "no": 20},
    "line": 29,
    "message": "agent starting: 'fix the type error'",
    "module": "agent",
    "name": "agent",
    "process": {"id": 12345, "name": "MainProcess"},
    "thread": {"id": 8794906944, "name": "MainThread"},
    "time": {"repr": "2026-06-19 14:23:01", "timestamp": 1750337981.0}
  }
}
```

This format ships directly to tools like Loki, Datadog, or a simple `jq` pipeline:

```bash
# Show only warnings and above from the log file.
jq 'select(.record.level.no >= 30)' /tmp/agent.log

# Count tool executions across a session.
jq 'select(.record.message | startswith("executing tool"))' /tmp/agent.log | wc -l
```

:::warning
The file sink and the stderr sink share the same `AGENT_LOG_LEVEL` threshold. There is no
mechanism today to set them to different levels. If you need verbose file logs alongside
quiet stderr output, you can call `setup_logging()` and then manually add a second sink with
`logger.add(...)` after startup.
:::

## Troubleshooting

**No log output at all**

`setup_logging()` removes loguru's default handler before installing the configured one. If
you import `logger` before calling `setup_logging()`, you get the loguru default (which also
writes to stderr, but with a different format). Call `setup_logging()` first, before any
other imports that use `logger`.

**Too much output**

Set `AGENT_LOG_LEVEL=WARNING` to see only warnings and errors. At that level a clean run
produces no stderr output at all.

**Log file not appearing**

Check that `AGENT_LOG_FILE` is set (not just exported in a subshell that `uv run` can't see).
Put it in `.env` and confirm `load_dotenv()` runs before `setup_logging()`.

**Tool exceptions not showing tracebacks**

The agent catches tool exceptions with `logger.exception(...)`, which records the traceback.
Tracebacks appear at the `ERROR` level. If your level is `WARNING` or above, you will see a
one-liner but no stack. Set `AGENT_LOG_LEVEL=DEBUG` or `INFO` to restore full tracebacks.

For more diagnostic techniques, see [Troubleshooting](../troubleshooting.md) and
[Debugging Streaming](../guides/debugging-streaming.md).

## Related pages

- [Settings Reference](./settings.md) — full table of `AGENT_*` environment variables.
- [Troubleshooting](../troubleshooting.md) — diagnosing common runtime failures.
- [Debugging Streaming](../guides/debugging-streaming.md) — inspecting chunk-by-chunk stream behaviour.
- [Development Workflow](../contributing/development-workflow.md) — running the test suite and iterating locally.
