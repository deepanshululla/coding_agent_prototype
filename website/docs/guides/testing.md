---
sidebar_position: 2
title: Testing the Agent
description: How to unit-test individual tools and integration-test the agent loop by mocking stream_response to yield canned OpenAI-format chunks.
---

# Testing the Agent

The codebase is split into two test targets that need different strategies:

- **Tools** (`src/tools.py`) are pure functions that read files, run subprocesses, and return strings. They can be tested directly without a real LLM.
- **The agent loop** (`src/agent.py`) coordinates streaming, tool dispatch, and message history. Testing it requires a fake LLM that yields deterministic chunks.

:::note
`src/tools.py` and `src/agent.py` are implemented, and `tests/test_tools.py` and `tests/test_agent.py` exist with a passing test suite. The patterns below reflect the shipped code and tests.
:::

---

## Project TDD approach

The project follows a test-first loop:

1. Write a failing test that exercises the smallest meaningful slice of new behavior. Run it and confirm it fails for the right reason (an assertion, not an import error).
2. Write the minimum code to make the test pass.
3. Refactor with the test as a safety net. Re-run after every change.
4. Repeat for the next slice.

For this project, that means writing the test for each tool function before implementing the function, and writing the loop test before wiring up the real LLM call.

---

## `pyproject.toml` — pythonpath configuration

Because `src/` is not a package (no `__init__.py`), pytest cannot import from it without help. Add this to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
```

With this in place, `from tools import TOOL_REGISTRY` works in any test file. Without it, you get `ModuleNotFoundError` immediately.

---

## Unit-testing tools (`tests/test_tools.py`)

Each tool function takes typed arguments and returns a string. Test them the same way you'd test any pure function — call them with known inputs, assert on the output.

### Example: `read_file`

```python
# tests/test_tools.py
import asyncio
import pytest
import tempfile
import os

from tools import read_file


def test_read_file_returns_contents(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("line one\nline two\nline three\n")
    result = asyncio.run(read_file(str(f)))
    assert "line one" in result
    assert "line three" in result


def test_read_file_respects_offset_and_limit(tmp_path):
    f = tmp_path / "numbered.txt"
    f.write_text("\n".join(f"line {i}" for i in range(10)))
    result = asyncio.run(read_file(str(f), offset=3, limit=2))
    assert "line 3" in result
    assert "line 4" in result
    assert "line 0" not in result


def test_read_file_missing_path_returns_error_string():
    result = asyncio.run(read_file("/nonexistent/path.txt"))
    # Must return an error string, not raise
    assert "error" in result.lower() or "no such" in result.lower()
```

The last test is the most important: tool errors must return a descriptive string, never raise an exception. The agent loop relies on this to reason about failures and try alternatives.

### Example: `edit_file`

```python
def test_edit_file_replaces_unique_string(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("def foo():\n    return 1\n")
    result = asyncio.run(edit_file(str(f), old_string="return 1", new_string="return 42"))
    assert result == "" or "ok" in result.lower()  # success signal
    assert "return 42" in f.read_text()


def test_edit_file_rejects_missing_old_string(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("def foo():\n    return 1\n")
    result = asyncio.run(edit_file(str(f), old_string="DOES_NOT_EXIST", new_string="x"))
    assert "not found" in result.lower() or "error" in result.lower()


def test_edit_file_rejects_non_unique_string(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("x = 1\nx = 1\n")
    result = asyncio.run(edit_file(str(f), old_string="x = 1", new_string="x = 2"))
    assert "unique" in result.lower() or "multiple" in result.lower() or "error" in result.lower()
```

### Example: `bash`

```python
def test_bash_captures_stdout():
    result = asyncio.run(bash("echo hello"))
    assert "hello" in result


def test_bash_captures_stderr():
    result = asyncio.run(bash("ls /nonexistent_dir_xyz 2>&1"))
    assert result  # some error output returned, not empty


def test_bash_includes_exit_code_on_failure():
    result = asyncio.run(bash("exit 1"))
    assert "exit" in result.lower() or "1" in result
```

### Structuring the test file

Group tests by tool so failures are easy to locate. A plain function grouping is enough — no classes needed:

```
tests/test_tools.py
  test_read_file_*
  test_write_file_*
  test_edit_file_*
  test_bash_*
  test_grep_*
  test_find_files_*
  test_list_dir_*
```

Run with:

```bash
uv run pytest tests/test_tools.py -v
```

---

## Integration-testing the loop (`tests/test_agent.py`)

The loop in `src/agent.py` calls `stream_response()` from `src/provider.py`. To test the loop without a real LLM, replace `stream_response` with an async generator that yields pre-built chunks.

### Building fake chunks

LiteLLM yields objects with a specific shape. For tests, create simple data classes or `MagicMock` objects that mirror the structure:

```python
# tests/test_agent.py
import asyncio
import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


def make_text_chunk(text: str, finish_reason=None):
    """Return a fake chunk that delivers a text fragment."""
    chunk = MagicMock()
    chunk.choices[0].delta.content = text
    chunk.choices[0].delta.tool_calls = None
    chunk.choices[0].finish_reason = finish_reason
    return chunk


def make_tool_chunk(index: int, tool_id: str = None, name: str = None, arguments: str = ""):
    """Return a fake chunk carrying a tool-call fragment."""
    tc = MagicMock()
    tc.index = index
    tc.id = tool_id
    tc.function = MagicMock()
    tc.function.name = name
    tc.function.arguments = arguments

    chunk = MagicMock()
    chunk.choices[0].delta.content = None
    chunk.choices[0].delta.tool_calls = [tc]
    chunk.choices[0].finish_reason = None
    return chunk
```

### Test: agent produces text output and stops

```python
async def fake_text_stream(messages, system_prompt):
    yield make_text_chunk("Hello, ")
    yield make_text_chunk("world!", finish_reason="stop")


def test_agent_prints_text_and_stops(capsys):
    with patch("agent.stream_response", side_effect=fake_text_stream):
        from agent import run_agent
        asyncio.run(run_agent("say hello"))

    captured = capsys.readouterr()
    assert "Hello, " in captured.out
    assert "world!" in captured.out
```

### Test: agent executes a tool call and sends back the result

This is the core loop test. The fake stream yields one tool-call (spread across two chunks to test fragment buffering), then yields a final text chunk after tool execution.

```python
call_count = 0

async def fake_tool_stream(messages, system_prompt):
    global call_count
    call_count += 1

    if call_count == 1:
        # First call: request a tool
        yield make_tool_chunk(0, tool_id="call_001", name="list_dir", arguments="")
        yield make_tool_chunk(0, arguments='{"path": "."}')
        final = make_text_chunk(None, finish_reason="tool_calls")
        final.choices[0].delta.content = None
        yield final
    else:
        # Second call: respond after seeing tool result
        yield make_text_chunk("Done.", finish_reason="stop")


def test_agent_executes_tool_and_continues(capsys):
    global call_count
    call_count = 0

    with patch("agent.stream_response", side_effect=fake_tool_stream):
        with patch("agent.TOOL_REGISTRY", {"list_dir": AsyncMock(return_value="src/")}):
            from agent import run_agent
            asyncio.run(run_agent("list the source files"))

    captured = capsys.readouterr()
    assert "Done." in captured.out
```

### Test: MAX_ITERATIONS guards against infinite loops

```python
async def infinite_tool_stream(messages, system_prompt):
    yield make_tool_chunk(0, tool_id="call_001", name="bash", arguments='{"cmd": "echo hi"}')
    yield make_text_chunk(None, finish_reason="tool_calls")


def test_agent_stops_at_max_iterations():
    # Should return without hanging even if tools keep being called
    with patch("agent.stream_response", side_effect=infinite_tool_stream):
        with patch("agent.TOOL_REGISTRY", {"bash": AsyncMock(return_value="hi")}):
            with patch("agent.MAX_ITERATIONS", 3):
                from agent import run_agent
                asyncio.run(run_agent("run forever"))
    # If we get here, the guard worked
```

---

## Running the full test suite

```bash
# All tests
uv run pytest -v

# Just tools
uv run pytest tests/test_tools.py -v

# Just agent loop
uv run pytest tests/test_agent.py -v

# Stop on first failure
uv run pytest -x
```

---

## Related pages

- [Contributing: Development Workflow](../contributing/development-workflow.md) — the full TDD loop, plan-first approach, and commit conventions
- [Architecture: The Agent Loop](../architecture/the-agent-loop.md) — how the phases A–E work in the real implementation
