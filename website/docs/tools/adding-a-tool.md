---
sidebar_position: 6
title: Adding a Tool
description: Step-by-step guide to adding a new tool, following the project's TDD loop from failing test to working implementation.
---

# Adding a Tool

Adding a tool means writing four things: a test, an async function, a JSON schema, and a registry entry. This page walks through a concrete example — a `count_lines` tool — following the project's TDD loop exactly.

:::note
The patterns here match the shipped `src/tools.py` and `tests/test_tools.py`.
:::

## Before you start

Check what already exists. The seven [built-in tools](./built-in-tools.md) cover most common operations. A new tool is worth adding when:

- No combination of existing tools can do the job cleanly.
- The operation is common enough that the model would reach for it repeatedly.
- The implementation is self-contained and testable without a running LLM.

## The TDD loop

The project's `CLAUDE.md` mandates test-first development for any new function. The loop is:

1. Write a failing test that exercises the smallest meaningful slice of the new behaviour.
2. Confirm it fails for the right reason (assertion error, not import error).
3. Write the minimum code to make it pass.
4. Refactor with the test as a safety net.
5. Repeat for the next slice.

## Worked example: `count_lines`

`count_lines` counts the number of lines in a file. Simple, but it illustrates every step.

### Step 1 — Write the failing test

Open `tests/test_tools.py` and add a test before writing any implementation:

```python
# tests/test_tools.py
import asyncio
import tempfile
import os
import pytest
from tools import count_lines   # will fail until we implement it


def test_count_lines_basic():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("line one\nline two\nline three\n")
        path = f.name
    try:
        result = asyncio.run(count_lines(path))
        assert result == "3"
    finally:
        os.unlink(path)


def test_count_lines_missing_file():
    result = asyncio.run(count_lines("/nonexistent/path.txt"))
    assert "not found" in result.lower()
```

Run the test and confirm the import fails:

```bash
uv run pytest tests/test_tools.py::test_count_lines_basic -v
# ImportError: cannot import name 'count_lines' from 'tools'
```

That's the right failure. The test is wired correctly.

### Step 2 — Write the async function

Add `count_lines` to `src/tools.py`. Remember: declare it `async def`, use `asyncio.to_thread` for the blocking file read, and return an error string on failure — never raise.

```python
# src/tools.py

async def count_lines(path: str) -> str:
    """Count the number of lines in a file."""
    def _count():
        return Path(path).read_text().count("\n")

    try:
        count = await asyncio.to_thread(_count)
        return str(count)
    except FileNotFoundError:
        return f"File not found: {path}"
    except Exception as e:
        return f"Error reading {path}: {e}"
```

Run the tests again:

```bash
uv run pytest tests/test_tools.py::test_count_lines_basic tests/test_tools.py::test_count_lines_missing_file -v
# PASSED
# PASSED
```

### Step 3 — Add the schema to `TOOLS_SCHEMA`

The schema goes in the `TOOLS_SCHEMA` list in `src/tools.py`. Use OpenAI format — `"type": "function"` wrapper, `"parameters"` key, not `"input_schema"`.

```python
# src/tools.py — append to TOOLS_SCHEMA

{
    "type": "function",
    "function": {
        "name": "count_lines",
        "description": (
            "Count the number of lines in a file. "
            "Useful for estimating file size before deciding whether to read it in chunks."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to count",
                },
            },
            "required": ["path"],
        },
    },
},
```

The description tells the model *when* to use this tool. Make it specific enough that the model reaches for it in the right situations.

### Step 4 — Register in `TOOL_REGISTRY`

Add the function to the registry dict:

```python
# src/tools.py — TOOL_REGISTRY

TOOL_REGISTRY: dict[str, callable] = {
    "read_file":   read_file,
    "write_file":  write_file,
    "edit_file":   edit_file,
    "bash":        bash,
    "grep":        grep,
    "find_files":  find_files,
    "list_dir":    list_dir,
    "count_lines": count_lines,   # ← new
}
```

The key must match the `"name"` in the schema exactly. A mismatch means the model can request the tool but the loop will return `"Unknown tool: count_lines"`.

### Step 5 — Mention it in the system prompt

Open `src/prompts.py` and add `count_lines` to the tool list in `build_system_prompt`:

```python
## Available Tools
- read_file: Read file contents, with optional line offset and limit
- bash: Execute shell commands (ls, git, grep, pytest, etc.)
- edit_file: Replace a specific string in a file with new content
- write_file: Create or overwrite a file with new content
- grep: Search for text patterns across files
- find_files: Find files by name pattern
- list_dir: List directory contents
- count_lines: Count the number of lines in a file    # ← new
```

The system prompt shapes the model's awareness of what tools exist. A tool absent from the prompt may go unused even if it's in the schema, because the model doesn't know to reach for it.

### Step 6 — Verify end-to-end

Run the full test suite:

```bash
uv run pytest tests/test_tools.py -v
```

Then do a manual smoke test with the CLI:

```bash
uv run main.py "how many lines does src/tools.py have?"
```

Watch the agent request `count_lines`, execute it, and incorporate the result in its answer. If it doesn't reach for the tool, check the schema description and the system prompt entry.

## Checklist

Use this before every new tool:

- [ ] Test written in `tests/test_tools.py` and confirmed failing before implementation
- [ ] Function declared `async def` with Python default values for optional parameters
- [ ] Blocking I/O wrapped in `await asyncio.to_thread(...)`
- [ ] All error paths return a descriptive string — no bare `raise`, no silent `except: pass`
- [ ] Schema added to `TOOLS_SCHEMA` with `"type": "function"` wrapper and `"parameters"` key
- [ ] `"name"` in schema matches the `TOOL_REGISTRY` key exactly
- [ ] Entry added to `TOOL_REGISTRY`
- [ ] Tool mentioned in `build_system_prompt()` in `src/prompts.py`
- [ ] All tests pass: `uv run pytest tests/test_tools.py -v`
- [ ] Manual smoke test with `uv run main.py "<task that would naturally use the tool>"`

## Related pages

- [Overview](./overview.md) — the three-part tool contract
- [Schema Format](./schema-format.md) — full annotated schema example
- [Error Handling](./error-handling.md) — how to write the error return paths
- [Built-in Tools](./built-in-tools.md) — the 7 existing tools to study as examples
