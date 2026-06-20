---
sidebar_position: 9
title: Phase 8 — System Prompt & CLI
description: Ground the agent with a dynamic system prompt (cwd, date, tool list), bound the loop with MAX_ITERATIONS, and package it as a CLI entry point.
---

# Phase 8 — System Prompt & CLI

:::note Starting point
Phase 7's parallel-executing loop — complete, but with no system prompt, no iteration cap, and no entry point. This phase ships it.
:::

The agent loop works, the tools are wired up, and parallel execution is live. Three things are still missing before you have a finished, runnable agent: a system prompt that tells the model *where it is* and *what it can do*, a hard iteration cap so a confused model can't loop forever, and a CLI entry point so you can invoke the agent from your terminal.

This phase adds all three. When you're done you'll have the complete agent — exactly what's in the repository.

## What you'll learn

- How `build_system_prompt` encodes the live working directory, today's date, and the tool list into the prompt at the moment the agent starts.
- Why a dynamic prompt beats a static constant — and what goes stale if you skip it.
- How `MAX_ITERATIONS = 30` bounds the inner loop and what happens when it trips.
- How `main.py` wires `load_dotenv`, `sys.argv`, and `asyncio.run` into a one-command CLI.

## Build it

### `src/prompts.py`

The system prompt is built once per `run_agent` call, not stored as a module-level constant. That way the `cwd` and `today` fields reflect actual runtime values.

```python
"""The system prompt builder.

Built per-run rather than stored as a static constant so it can fold in the live working
directory and date. The tool list here must stay in sync with ``tools.TOOL_REGISTRY``.
"""

from __future__ import annotations

import os
from datetime import date


def build_system_prompt(cwd: str | None = None, extra: str = "") -> str:
    cwd = cwd or os.getcwd()
    today = date.today().isoformat()

    return f"""You are an expert coding assistant running inside a terminal agent harness.
You help users by reading files, executing shell commands, editing code, and writing new files.

## Available Tools
- read_file: Read file contents, with optional line offset and limit
- write_file: Create or overwrite a file with new content
- edit_file: Replace a specific string in a file with new content
- bash: Execute shell commands (ls, git, grep, pytest, etc.)
- grep: Search for text patterns across files
- find_files: Find files by name pattern
- list_dir: List directory contents

## Guidelines
- Start by understanding the task. Use read_file or list_dir to explore before making changes.
- Prefer targeted edits (edit_file) over full rewrites (write_file) for existing files.
- Always verify changes with bash (e.g., run tests, check syntax) after editing.
- When a tool returns an error, reason about it and try an alternative approach.
- Be concise in your text responses. Let the tools do the work.

## Environment
Working directory: {cwd}
Today's date: {today}

{extra}""".rstrip() + "\n"
```

The function accepts an optional `cwd` override (useful in tests) and an `extra` string that lets callers append context without touching the template.

### `MAX_ITERATIONS` in `src/agent.py`

At the top of `agent.py`, alongside the imports, add the constant:

```python
MAX_ITERATIONS = 30
```

The inner loop already references it:

```python
while (has_more_tool_calls or pending_messages) and iteration < MAX_ITERATIONS:
    iteration += 1
    ...
```

When `iteration` reaches 30 the inner loop exits silently. The outer loop then breaks (no follow-up source in v1) and `run_agent` returns the message history. The model doesn't get a special error; it simply stops. In practice a well-formed task completes in 5–10 iterations; hitting 30 signals either a runaway loop or an unusually large task.

### `main.py`

The CLI entry point lives at the repo root, not inside `src/`. It adds `src/` to `sys.path` (since it's not an installed package) and delegates everything to `run_agent`.

```python
"""CLI entrypoint.

Usage:
    uv run main.py "add type hints to all functions in tools.py"

With no argument, prompts for a task interactively.
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

# src/ is not a package; make its modules importable.
sys.path.insert(0, str(Path(__file__).parent / "src"))

from agent import run_agent  # noqa: E402


async def main() -> None:
    load_dotenv()
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Task: ")
    if not task.strip():
        print("No task provided.")
        return
    await run_agent(task)


if __name__ == "__main__":
    asyncio.run(main())
```

Key points:

- `load_dotenv()` reads `ANTHROPIC_API_KEY` (or whichever provider key you set) from a `.env` file. LiteLLM picks it up automatically via the environment.
- Task from `sys.argv` or interactive `input` — no argparse needed at this scale.
- `asyncio.run(main())` is the canonical way to enter an async entry point from synchronous Python.

### Wiring the system prompt into `agent.py`

`build_system_prompt()` is already called at the top of `run_agent`:

```python
async def run_agent(task: str) -> list[dict]:
    system_prompt = build_system_prompt()
    messages: list[dict] = [{"role": "user", "content": task}]
    ...
```

And passed into `stream_response` on every inner-loop iteration:

```python
async for chunk in stream_response(messages, system_prompt):
    ...
```

The system prompt is computed once and reused across all iterations of the inner loop. It doesn't change mid-task — the cwd and date captured at the start of the run are the correct values for the whole conversation.

## Test it

Write the tests first, run them (they'll fail because the function doesn't exist yet or the constant isn't set), then add the code above.

Add this file as `tests/test_prompts.py`:

```python
"""Tests for the system prompt builder."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import prompts


def test_prompt_contains_cwd(tmp_path):
    result = prompts.build_system_prompt(cwd=str(tmp_path))
    assert str(tmp_path) in result


def test_prompt_contains_today():
    result = prompts.build_system_prompt()
    today = date.today().isoformat()
    assert today in result


def test_prompt_contains_all_tool_names():
    result = prompts.build_system_prompt()
    for name in ("read_file", "write_file", "edit_file", "bash", "grep", "find_files", "list_dir"):
        assert name in result, f"Tool {name!r} missing from system prompt"


def test_prompt_extra_is_appended():
    result = prompts.build_system_prompt(extra="CUSTOM MARKER")
    assert "CUSTOM MARKER" in result
```

Add a `MAX_ITERATIONS` check to `tests/test_agent.py`:

```python
import agent


def test_max_iterations_is_set():
    """Ensure the iteration cap is defined and reasonable."""
    assert isinstance(agent.MAX_ITERATIONS, int)
    assert 1 <= agent.MAX_ITERATIONS <= 100
```

Run all tests:

```bash
uv run pytest tests/ -v
```

Expected (all green, combining tests from phases 6, 7, and 8):

```
tests/test_tools.py::test_read_file_missing_returns_error_not_raise PASSED
tests/test_tools.py::test_read_file_returns_contents PASSED
tests/test_tools.py::test_read_file_offset_and_limit PASSED
tests/test_tools.py::test_write_file_creates_parent_dirs PASSED
tests/test_tools.py::test_edit_file_replaces_unique_string PASSED
tests/test_tools.py::test_edit_file_errors_when_not_found PASSED
tests/test_tools.py::test_edit_file_errors_when_not_unique PASSED
tests/test_tools.py::test_bash_runs_command PASSED
tests/test_tools.py::test_bash_reports_exit_code PASSED
tests/test_tools.py::test_registry_matches_schema PASSED
tests/test_agent.py::test_parallel_dispatch_two_tools PASSED
tests/test_agent.py::test_unknown_tool_returns_error_not_raise PASSED
tests/test_agent.py::test_max_iterations_is_set PASSED
tests/test_prompts.py::test_prompt_contains_cwd PASSED
tests/test_prompts.py::test_prompt_contains_today PASSED
tests/test_prompts.py::test_prompt_contains_all_tool_names PASSED
tests/test_prompts.py::test_prompt_extra_is_appended PASSED
```

### Behavior (BDD)

Verify this phase as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Feature: System prompt content and iteration cap
  build_system_prompt encodes live runtime values; MAX_ITERATIONS guarantees
  the inner loop terminates; the CLI resolves the task from argv or stdin.

  Scenario: the system prompt contains the cwd, today's date, and all 7 tool names
    Given build_system_prompt is called with a known cwd "/tmp/test-workspace"
    When the returned prompt string is inspected
    Then the prompt contains "/tmp/test-workspace"
    And the prompt contains today's date in ISO-8601 format
    And the prompt contains each of "read_file", "write_file", "edit_file", "bash", "grep", "find_files", "list_dir"

  Scenario: the loop halts at MAX_ITERATIONS when the model never stops
    Given a scripted model that always responds with a list_dir tool call and never emits finish_reason "stop"
    And MAX_ITERATIONS is patched to 3
    When run_agent runs
    Then at most 3 tool-call messages are dispatched
    And run_agent returns without hanging

  Scenario: the extra argument is appended verbatim to the system prompt
    Given build_system_prompt is called with extra="DEPLOY_ENV=staging"
    When the returned prompt string is inspected
    Then the prompt contains "DEPLOY_ENV=staging"
    And the extra text appears after the standard environment block

  Scenario: the CLI reads the task from argv and falls back to stdin
    Given main.py is invoked with sys.argv ["main.py", "list", "all", ".py", "files"]
    And a scripted model that returns a plain-text answer immediately
    When asyncio.run(main()) executes
    Then run_agent is called with task "list all .py files" (argv joined)
    Given main.py is invoked with sys.argv ["main.py"] and stdin contains "describe the repo"
    When asyncio.run(main()) executes
    Then run_agent is called with task "describe the repo" (stdin value)
```

Run this as an integration scenario with the [BDD framework](../guides/bdd-integration-testing.md) — `pytest-bdd` over the `ScriptedLLM` harness from Phase 9. The unit test above proves the mechanism; this scenario specifies the *behavior*.

:::note
The system prompt built by `build_system_prompt()` contains the working directory, today's date, and all 7 tool names (`read_file`, `write_file`, `edit_file`, `bash`, `grep`, `find_files`, `list_dir`). A complementary BDD scenario can assert that all 7 names appear in the prompt passed to the scripted LLM's first turn.
:::

## Run it

```bash
uv run main.py "list all .py files in the project"
```

Expected output (abridged — the exact tool calls depend on how the model chooses to explore):

```
▸ find_files
  [executing find_files {'pattern': '*.py', 'path': '.'}]
  [✓ find_files: 189 chars]

Here are all the Python files in the project:

- main.py
- src/agent.py
- src/tools.py
- src/prompts.py
- src/provider.py
- src/types_.py
- tests/test_tools.py
- tests/test_agent.py
- tests/test_prompts.py
```

Try an interactive session (no argument):

```bash
uv run main.py
Task: read src/prompts.py and summarise what build_system_prompt does
```

:::tip
Set `ANTHROPIC_API_KEY` in a `.env` file at the repo root before running. LiteLLM reads it automatically. To use a different model swap the `MODEL` constant in `src/provider.py` — `"gemini/gemini-2.0-flash"` or `"gpt-4o"` work without any other changes.
:::

## Recap

You now have the full agent. The pieces fit together like this:

```
main.py
  └─ asyncio.run(run_agent(task))
        └─ build_system_prompt()          # cwd + date + tool list
        └─ inner loop (MAX_ITERATIONS=30)
              └─ stream_response()        # LiteLLM → OpenAI chunks
              └─ _execute_tools_parallel()
                    └─ _execute_one_tool()
                          └─ TOOL_REGISTRY[name](**args)
```

Every module you've built across phases 1–8 is in play: `types_` for `ToolResult`, `tools` for the seven implementations and schemas, `provider` for the streaming LiteLLM call, `prompts` for the dynamic system prompt, and `agent` for the loop that ties them together.

To understand how the system prompt shapes model behaviour, see [concepts/system-prompts.md](../concepts/system-prompts.md). For the full CLI reference (flags, env vars, model selection), see [reference/cli.md](../reference/cli.md). For a complete walkthrough of one agent turn from user input to final reply, see [architecture/the-agent-loop.md](../architecture/the-agent-loop.md).
