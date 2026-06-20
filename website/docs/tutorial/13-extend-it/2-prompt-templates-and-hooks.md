---
sidebar_position: 2
title: "Layer 13.2 — Prompt Templates & Hooks"
description: Add per-session instruction injection via the extra parameter and beforeToolCall/afterToolCall hook points in _execute_one_tool.
---

# Layer 13.2 — Prompt Templates & Hooks

:::note Implemented
This step is implemented on branch `step/phase-13-2-prompt-templates-and-hooks` (plan: `plans/tutorial/phase-13-2-prompt-templates-and-hooks.md`).
:::

:::note Starting point
Layer 13.1 complete: `src/project_instructions.py` loads `AGENTS.md` / `CLAUDE.md` into the system prompt via `extra`. The test suite passes.
:::

Project instructions cover *always-on* conventions. But sometimes you want to inject extra context for just this session — "focus only on `src/tools.py`", or "output in JSON". And sometimes you want code to run *around* every tool call: log what the agent touched, gate a destructive command behind a confirmation prompt, or redact secrets from tool output before they enter message history.

This layer adds two things:

1. **Prompt templates** — how `build_system_prompt`'s `extra` parameter lets you compose per-session overrides alongside project instructions.
2. **Tool-call hooks** — `beforeToolCall` and `afterToolCall` hook points in `_execute_one_tool`, following the pattern from pi.dev.

The full `extra` API is documented in [Prompt Templates](../../customization/prompt-templates.md). The hook design is in [Extensions & Hooks](../../customization/extensions-and-hooks.md).

## What you'll learn

- How to compose multiple strings into `extra` without changing `build_system_prompt`.
- Where `beforeToolCall` and `afterToolCall` slot into `_execute_one_tool`.
- How to write a logging `afterToolCall` hook and an async-safe `beforeToolCall` permission gate.
- Why hooks are plain async functions passed as arguments — not a plugin registry.

## Build it

### Step 1 — Compose per-session overrides into `extra`

`build_system_prompt` already accepts `extra`. Combine project instructions with any per-session override by concatenating:

```python
# main.py (updated)
import asyncio
import os
import sys

from src.agent import run_agent
from src.prompts import build_system_prompt
from src.project_instructions import load_project_instructions


async def main() -> None:
    task = " ".join(sys.argv[1:]) or input("Task: ")
    cwd = os.getcwd()

    # Per-session override from env var (or leave empty)
    session_override = os.environ.get("AGENT_SESSION_CONTEXT", "")

    extra = "\n\n".join(filter(None, [
        load_project_instructions(cwd),
        session_override,
    ]))

    system_prompt = build_system_prompt(cwd=cwd, extra=extra)
    await run_agent(task, system_prompt=system_prompt)


if __name__ == "__main__":
    asyncio.run(main())
```

Now callers can inject context without modifying any source file:

```bash
AGENT_SESSION_CONTEXT="Focus only on src/tools.py for this session." \
    uv run main.py "add type hints to all public functions"
```

The injected text lands at the bottom of the system prompt, after the static guidelines and the project instructions block.

### Step 2 — Add hook points in `_execute_one_tool`

Open `src/agent.py`. The `_execute_one_tool` function currently looks up the tool and calls it. Add two hook call sites — one before execution and one after:

```python
# src/agent.py — _execute_one_tool (updated signature)

async def _execute_one_tool(
    tool_call: dict,
    before_tool_call=None,   # async (name, args) -> bool | None
    after_tool_call=None,    # async (name, args, result) -> str
) -> ToolResult:
    name = tool_call["name"]
    args = tool_call["input"]

    # ── beforeToolCall ──────────────────────────────────────────────────
    if before_tool_call is not None:
        approved = await before_tool_call(name, args)
        if approved is False:
            return ToolResult(
                tool_call["id"], name, f"Tool call denied: {name}", is_error=True
            )

    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
    try:
        result = await fn(**args)
    except Exception as e:
        return ToolResult(tool_call["id"], name, f"Error: {e}", is_error=True)

    # ── afterToolCall ───────────────────────────────────────────────────
    if after_tool_call is not None:
        result = await after_tool_call(name, args, result)

    return ToolResult(tool_call["id"], name, result)
```

Thread the new parameters through `_execute_tools_parallel` and `run_agent`:

```python
# src/agent.py — _execute_tools_parallel

async def _execute_tools_parallel(
    tool_calls: list[dict],
    before_tool_call=None,
    after_tool_call=None,
) -> list[ToolResult]:
    return list(await asyncio.gather(
        *[
            _execute_one_tool(tc, before_tool_call, after_tool_call)
            for tc in tool_calls
        ]
    ))


# src/agent.py — run_agent signature

async def run_agent(
    task: str,
    system_prompt: str | None = None,
    before_tool_call=None,
    after_tool_call=None,
) -> list[dict]:
    ...
    # pass hooks into _execute_tools_parallel calls
```

### Step 3 — Write a logging `afterToolCall` hook

```python
# src/hooks.py

"""Ready-to-use hook implementations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(".agent-tool-log.jsonl")


async def log_after_tool_call(name: str, args: dict, result: str) -> str:
    """Log every tool call to a JSONL file; return result unchanged."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": name,
        "args": args,
        "result_len": len(result),
        "result_preview": result[:200],
    }
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return result  # pass through unchanged
```

Wire it from `main.py`:

```python
from src.hooks import log_after_tool_call

await run_agent(task, system_prompt=system_prompt, after_tool_call=log_after_tool_call)
```

### Step 4 — Write an async-safe `beforeToolCall` permission gate

```python
# src/hooks.py (continued)

import asyncio

ALWAYS_ALLOW = frozenset({"read_file", "list_dir", "grep", "find_files"})


async def confirm_before_tool_call(name: str, args: dict) -> bool:
    """Prompt the user before any write/execute tool. Read-only tools pass silently."""
    if name in ALWAYS_ALLOW:
        return True
    loop = asyncio.get_event_loop()
    formatted = ", ".join(f"{k}={v!r}" for k, v in args.items())
    answer = await loop.run_in_executor(
        None, input, f"\n  Allow {name}({formatted})? [y/N] "
    )
    return answer.strip().lower() == "y"
```

:::warning Parallel tool calls and blocking prompts
`_execute_tools_parallel` dispatches via `asyncio.gather`. If two tool calls arrive in the same batch, both hooks fire concurrently. `run_in_executor` keeps the event loop alive during the `input()` call, but the user sees two prompts simultaneously. For interactive gates, consider serializing tool dispatch when `before_tool_call` is set, or collect all approvals before dispatching. See [Extensions & Hooks](../../customization/extensions-and-hooks.md#implementing-a-beforetoolcall-permission-prompt) for the fuller discussion.
:::

## Test it

### Behavior (BDD)

Verify this layer as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Scenario: Injected template appears in the prompt AND beforeToolCall hook fires
  Given AGENT_SESSION_CONTEXT is set to "Output responses in JSON only"
  And a beforeToolCall hook that records each tool name in a list
  When the agent is initialized and processes a task that triggers a read_file call
  Then the system prompt contains "Output responses in JSON only"
  And the beforeToolCall hook's recorded list contains "read_file"
  And the tool result is returned normally (hook returned True)
```

Run this as an integration scenario with the [BDD framework](../../guides/bdd-integration-testing.md).

The scenario fails before the change because `_execute_one_tool` has no hook parameter and `AGENT_SESSION_CONTEXT` is never consulted. After the change, the hook fires and the override appears in the prompt.

### Existing tests

Hooks default to `None`, so all existing tests pass without change:

```bash
uv run pytest -q
```

Any test that directly calls `_execute_one_tool` without the new parameters continues to work because the hook arguments are keyword-optional with `None` defaults.

## Run it

```bash
# Per-session context injection
AGENT_SESSION_CONTEXT="This session: focus on performance bottlenecks." \
    uv run main.py "profile the agent loop"

# Enable tool logging
uv run python -c "
import asyncio
from src.agent import run_agent
from src.prompts import build_system_prompt
from src.hooks import log_after_tool_call

async def main():
    sp = build_system_prompt()
    await run_agent('list the src directory', system_prompt=sp,
                    after_tool_call=log_after_tool_call)

asyncio.run(main())
"
# Inspect the log:
cat .agent-tool-log.jsonl
```

:::tip Architecture pattern
The before/after tool hooks are exactly where the [Command](../../architecture-patterns/command-pattern.md) and [Policy Engine](../../architecture-patterns/policy-engine.md) patterns plug in.
:::

## Recap

`extra` composes per-session overrides alongside project instructions without touching `build_system_prompt`. The two hook points in `_execute_one_tool` — `beforeToolCall` and `afterToolCall` — let you log, gate, redact, or transform every tool interaction as plain async functions. The loop itself is unchanged.

The next step composes the agent's behavior from named instruction blocks — skills — controlled by an environment variable.

→ [Layer 13.3 — Skills](./3-skills.md)
