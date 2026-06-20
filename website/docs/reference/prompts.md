---
sidebar_position: 4
title: "prompts.py"
description: The system prompt builder — dynamically injects working directory, today's date, and the tool list.
---

# prompts.py

`src/prompts.py` contains one function: `build_system_prompt`. It produces the system prompt string that frames every conversation. The prompt is built dynamically so the model always has accurate context about the environment it is running in. See [system prompts](../concepts/system-prompts.md) for a conceptual explanation of what the system prompt does and why it matters.

:::note
The signature and behavior described here reflect the shipped `src/prompts.py`.
:::

---

## Functions

### `build_system_prompt`

```python
def build_system_prompt(cwd: str | None = None, extra: str = "") -> str
```

Builds and returns the system prompt string. Called once at the start of `run_agent`, before the first message is sent to the model.

**Parameters**

| Parameter | Type           | Default  | Description                                                                             |
|-----------|----------------|----------|-----------------------------------------------------------------------------------------|
| `cwd`     | `str \| None`  | `None`   | Working directory to embed. If `None`, defaults to `os.getcwd()` at call time.          |
| `extra`   | `str`          | `""`     | Optional extra instructions appended at the end. Useful for injecting task-specific context without modifying the base prompt. |

**Returns** `str` — the complete system prompt, ready to pass as the `system_prompt` argument to `stream_response`.

**Raises** Does not raise.

---

## What the prompt interpolates

The returned string embeds three dynamic values:

| Placeholder        | Source                     | Example value                    |
|--------------------|----------------------------|----------------------------------|
| Working directory  | `cwd or os.getcwd()`       | `/Users/alice/projects/myapp`    |
| Today's date       | `date.today().isoformat()` | `2026-06-19`                     |
| Tool list          | Hardcoded in the template  | `read_file`, `bash`, …           |

The date prevents the model from making stale assumptions about when "now" is. The working directory helps the model construct correct relative and absolute paths when calling tools.

---

## Prompt structure

```python
import os
from datetime import date

def build_system_prompt(cwd: str | None = None, extra: str = "") -> str:
    cwd = cwd or os.getcwd()
    today = date.today().isoformat()

    return f"""You are an expert coding assistant running inside a terminal agent harness.
You help users by reading files, executing shell commands, editing code, and writing new files.

## Available Tools
- read_file: Read file contents, with optional line offset and limit
- bash: Execute shell commands (ls, git, grep, pytest, etc.)
- edit_file: Replace a specific string in a file with new content
- write_file: Create or overwrite a file with new content
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

{extra}"""
```

The `extra` parameter is appended at the end of the `## Environment` block. Keep it short — it runs on every turn and consumes tokens.

---

## Usage

```python
from prompts import build_system_prompt

# Default: uses os.getcwd() and today's date
prompt = build_system_prompt()

# Override the working directory (e.g., in tests)
prompt = build_system_prompt(cwd="/tmp/test-workspace")

# Inject extra context for a specific task
prompt = build_system_prompt(extra="Focus only on the `src/` directory. Do not touch tests.")
```

:::tip
In tests, always pass an explicit `cwd` to `build_system_prompt` so the prompt is deterministic regardless of where the test runner is invoked from.
:::

---

## Design notes

Pi builds its system prompt dynamically too, using a "skills" abstraction that lets different capabilities inject their own sections. This implementation is simpler: one function, one f-string, one call site. The `extra` parameter gives you an escape hatch for the cases where you need to inject something without restructuring the whole template.

The tool list in the prompt is hardcoded to match `TOOLS_SCHEMA` in `tools.py`. If you add a new tool, update both `TOOLS_SCHEMA`/`TOOL_REGISTRY` in `tools.py` and the `## Available Tools` section here.

---

## Related pages

- [System prompts](../concepts/system-prompts.md) — why the system prompt matters and what it controls
- [provider.py](./provider.md) — `stream_response` receives the output of `build_system_prompt`
- [agent.py](./agent.md) — calls `build_system_prompt()` once at startup
- [tools.py](./tools.md) — the 7 tools listed in the prompt
