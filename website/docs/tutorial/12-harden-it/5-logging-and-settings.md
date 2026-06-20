---
sidebar_position: 5
title: "Layer 12.5 — Logging & Settings"
description: Route diagnostics to stderr with loguru and centralise every AGENT_* tunable in a single config reader so tool events are observable without polluting the model's output stream.
---

# Layer 12.5 — Logging & Settings

:::note Implemented
This step is implemented on branch `step/phase-12-5-logging-and-settings` (plan: `plans/tutorial/phase-12-5-logging-and-settings.md`).
:::

:::note Starting point
The hardened agent from Layer 12.4: a command allowlist, a policy engine with permission modes, and optional worktree sandboxing. The agent is safe to run, but when something goes wrong — a tool call is denied, an unexpected command appears, the loop hits `MAX_ITERATIONS` — the only signal is whatever the model printed to stdout. Diagnostics and configuration are scattered across module-level constants.
:::

This layer closes the observability gap with two small additions:

1. **Loguru diagnostics on stderr** — tool lifecycle events (start, result, error, iteration count) go to stderr so stdout stays clean for the model's output. You can crank verbosity to `DEBUG` without adding noise to the agent's response stream.
2. **A centralised `src/config.py` reader** — every `AGENT_*` environment variable in one place, so other modules import resolved values instead of calling `os.environ` ad hoc.

The logging design is documented in [Logging](../../operations/logging.md). The full table of tunables is in [Settings Reference](../../operations/settings.md).

## What you'll learn

- How to keep stdout (the model's output) and stderr (diagnostics) cleanly separated.
- How to wire loguru with a single `setup_logging()` call in `main.py`.
- Which events to log at which level (`DEBUG` for per-call detail, `INFO` for lifecycle, `WARNING` for recoverable problems).
- How `src/config.py` centralises `AGENT_*` reads so defaults and env overrides live in one module.

## Build it

### Step 1 — Create `src/logging_config.py`

```python
# src/logging_config.py

"""Loguru setup for the coding agent.

Call setup_logging() once in main.py, before any other src import.
All other modules import `logger` from this module — do not create
separate loguru loggers.

Two channels:
  stdout  — model streamed text + tool markers (managed by agent.py print() calls)
  stderr  — diagnostics: tool lifecycle, iteration counts, errors (loguru)

With AGENT_LOG_LEVEL=DEBUG you see every tool call on stderr while
stdout shows only the model's response.
"""

import os
import sys
from loguru import logger

_configured = False


def setup_logging() -> None:
    """Configure loguru. Idempotent — safe to call more than once."""
    global _configured
    if _configured:
        return

    # Remove loguru's default handler (writes to stderr with its own format).
    logger.remove()

    level = os.environ.get("AGENT_LOG_LEVEL", "INFO").upper()

    # stderr sink — human-readable, coloured.
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | "
               "<cyan>{name}</cyan> - {message}",
        colorize=True,
    )

    # Optional file sink — rotating JSON for log aggregators.
    log_file = os.environ.get("AGENT_LOG_FILE")
    if log_file:
        logger.add(
            log_file,
            level=level,
            rotation="10 MB",
            retention=5,
            serialize=True,   # one JSON object per line
        )

    logger.debug("logging configured at level {}", level)
    _configured = True


__all__ = ["logger", "setup_logging"]
```

### Step 2 — Create `src/config.py`

```python
# src/config.py

"""Centralised reader for AGENT_* environment variables.

Every module that needs a tunable imports it from here:
    from config import MAX_ITERATIONS, BASH_TIMEOUT

Defaults match the shipped constants so behaviour is identical when
nothing is set. load_dotenv() in main.py must run before config is
imported so .env is in os.environ when these module-level reads happen.
"""

import os


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"{name} must be an integer, got {raw!r}")


def _csv(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


# ── Model / provider ─────────────────────────────────────────────────────────
MODEL = os.environ.get("AGENT_MODEL", "claude-sonnet-4-5")
MAX_TOKENS = _int("AGENT_MAX_TOKENS", 8096)

# ── Loop ─────────────────────────────────────────────────────────────────────
MAX_ITERATIONS = _int("AGENT_MAX_ITERATIONS", 30)
SYSTEM_PROMPT_EXTRA = os.environ.get("AGENT_SYSTEM_PROMPT_EXTRA", "")

# ── Tools ────────────────────────────────────────────────────────────────────
BASH_TIMEOUT = _int("AGENT_BASH_TIMEOUT", 30)
BASH_OUTPUT_LIMIT = _int("AGENT_BASH_OUTPUT_LIMIT", 10_000)
FIND_LIMIT = _int("AGENT_FIND_LIMIT", 200)
READ_LIMIT = _int("AGENT_READ_LIMIT", 2000)

# ── Features ─────────────────────────────────────────────────────────────────
BASH_ALLOWLIST = _csv("AGENT_BASH_ALLOWLIST", [])
PERMISSION_MODE = os.environ.get("AGENT_PERMISSION_MODE", "auto")
UI = os.environ.get("AGENT_UI", "stdout")
THEME = os.environ.get("AGENT_THEME", "dark")
MCP_CONFIG = os.environ.get("AGENT_MCP_CONFIG")
```

:::tip Fail closed on bad input
`_int` raises `SystemExit` on a non-integer so a typo (`AGENT_MAX_ITERATIONS=lots`) stops the run immediately with a clear message instead of silently using the default. Security-sensitive variables (`AGENT_BASH_ALLOWLIST`) default to the **safe** value (empty list = allowlist gate inactive) so a missing config never silently widens permissions.
:::

### Step 3 — Wire logging into `main.py`

`setup_logging()` must be called before any import of `logger` from other modules:

```python
# main.py
import asyncio
import sys
from dotenv import load_dotenv
from logging_config import setup_logging


async def main() -> None:
    load_dotenv()
    setup_logging()   # reads AGENT_LOG_LEVEL; default INFO

    args = sys.argv[1:]
    if args and args[0] == "--sandbox":
        task = " ".join(args[1:]) or input("Task: ")
        from sandbox import run_in_worktree
        worktree = await run_in_worktree(task)
        print(f"\n--- Agent finished in worktree: {worktree}")
    else:
        task = " ".join(args) or input("Task: ")
        from agent import run_agent
        await run_agent(task)


if __name__ == "__main__":
    asyncio.run(main())
```

### Step 4 — Replace `print` diagnostics in `agent.py` with `logger` calls

The `[executing …]` and `[✓ …]` lines currently print to stdout alongside the model's output. Move them to `logger` on stderr:

```python
# src/agent.py (imports at top)
from logging_config import logger
from config import MAX_ITERATIONS
```

In `run_agent`:

```diff
+    logger.info("agent starting: {!r}", task)
     iteration = 0
     while ...:
         iteration += 1
+        logger.debug("iteration {}/{}", iteration, MAX_ITERATIONS)
         ...
+    logger.info("agent finished after {} iteration(s)", iteration)
```

In `_execute_one_tool`, replace the two `print` statements:

```diff
-    print(f"  [executing {name} {args}]")
+    logger.debug("executing tool {} with {}", name, args)
     ...
-    print(f"  [✓ {name}: {len(result)} chars]")
+    logger.debug("tool {} ok: {} chars", name, len(result))
```

For the unknown-tool and exception branches:

```diff
     if fn is None:
+        logger.warning("unknown tool requested: {}", name)
         return ToolResult(...)
     try:
         ...
     except Exception as e:
+        logger.exception("tool {} raised", name)
         return ToolResult(...)
```

Use `logger.exception(...)` (not `logger.error(...)`) inside `except` blocks — it automatically captures and formats the current traceback.

### Step 5 — Update other modules to use `config`

```python
# src/provider.py
from config import MODEL, MAX_TOKENS

# src/tools.py
from config import BASH_TIMEOUT, BASH_OUTPUT_LIMIT, FIND_LIMIT, READ_LIMIT
```

Remove the corresponding module-level constants from those files; `config.py` is now the single source of truth.

## Test it

### Behavior (BDD)

Verify this layer as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Scenario: Tool lifecycle events appear on stderr, not stdout, at DEBUG level
  Given the agent with loguru configured via setup_logging()
  And AGENT_LOG_LEVEL=DEBUG is set in the environment
  When the agent processes a task that calls one tool (e.g. read_file)
  Then stderr contains "executing tool read_file with" at DEBUG level
  And stderr contains "tool read_file ok:" at DEBUG level
  And stdout contains only the model's streamed text response
  And stdout does not contain "[executing" or "[✓"
```

Run this as an integration scenario with the [BDD framework](../../guides/bdd-integration-testing.md).

The scenario fails **before** this layer (`[executing …]` and `[✓ …]` appear on stdout). After this layer it passes: those lines move to stderr under the `logger.debug` calls, and stdout is clean model output.

## Run it

```bash
# Default INFO level: only lifecycle events on stderr.
uv run main.py "list the Python files in src/"

# DEBUG level: every tool call appears on stderr.
AGENT_LOG_LEVEL=DEBUG uv run main.py "list the Python files in src/"
# Terminal shows model output on stdout interleaved with debug lines on stderr.

# Capture only the model's answer; diagnostics go to the terminal.
AGENT_LOG_LEVEL=DEBUG uv run main.py "list the Python files in src/" > result.txt

# Suppress diagnostics entirely.
uv run main.py "list the Python files in src/" 2>/dev/null

# Write a JSON log file for later analysis.
AGENT_LOG_FILE=/tmp/agent.log uv run main.py "run the test suite"
jq '.record.message' /tmp/agent.log
```

### Sample stderr at DEBUG

```
14:23:01 | INFO    | agent - agent starting: 'list the Python files in src/'
14:23:01 | DEBUG   | agent - iteration 1/30
14:23:02 | DEBUG   | agent - executing tool bash with {'command': 'ls src/'}
14:23:02 | DEBUG   | agent - tool bash ok: 87 chars
14:23:02 | INFO    | agent - agent finished after 1 iteration(s)
```

Stdout at the same time contains only the model's streamed response.

:::tip Architecture pattern
Structured diagnostics are the seed of an [event-sourced run log](../../architecture-patterns/event-sourcing.md) — an append-only record for debugging, evals, and replay.
:::

## Recap

Phase 12 — Harden It — is complete. The five layers compose into a defence-in-depth stack:

| Layer | What it adds |
|---|---|
| 12.1 Security Model | Threat model; establishes why the guards exist |
| 12.2 Command Allowlist | Default-deny gate on `bash`; shell-parsing trap closed |
| 12.3 Permissions & Modes | `PolicyEngine` + `AGENT_PERMISSION_MODE`; read-only / ask / auto |
| 12.4 Sandboxing | Worktree + optional container; writes land on a throwaway branch |
| 12.5 Logging & Settings | Loguru on stderr; `config.py` centralises all tunables |

Each layer is independently deployable and testable. Together they let you run the agent against real codebases with a degree of confidence that none of the defaults provide.

The next phase extends the agent with project-level instructions, skills, and custom tool plugins.

→ [Phase 13 — Extend It: Layer 13.1 — Project Instructions](../13-extend-it/1-project-instructions.md)
