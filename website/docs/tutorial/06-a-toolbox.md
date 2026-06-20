---
sidebar_position: 7
title: Phase 6 — A Toolbox
description: Grow from one tool to seven behind a registry, and learn the cardinal contract — tools never raise, they return descriptive error strings.
---

# Phase 6 — A Toolbox

:::note Starting point
Phase 5's loop, which streams and dispatches a single tool. This phase grows that to all seven tools behind a registry.
:::

So far the agent can call exactly one tool: `read_file`. That's enough to prove the loop works, but not enough to do real work. This phase adds the remaining six tools, pulls them all behind a registry, and codifies **the cardinal contract**: a tool never raises a Python exception — on failure it returns a descriptive `"Error: ..."` string and the loop marks `is_error=True`.

## What you'll learn

- How to structure a tool: async function + JSON schema + registry entry — three wired together.
- Why blocking I/O (`subprocess`, `Path.read_text`) must be wrapped in `asyncio.to_thread`.
- How `BASH_TIMEOUT`, `BASH_OUTPUT_LIMIT`, and `FIND_LIMIT` keep output from blowing the context window.
- Why the uniqueness check in `edit_file` matters — and what error the model gets if it fails.
- How the never-raise contract lets the model reason about failures instead of crashing.

## Build it

Open `src/tools.py`. At the start of phase 5 it had only `read_file`, its schema, and a registry with one entry. Replace the file with the full seven-tool implementation:

```python
"""The seven tools the agent can call, plus their schemas and the registry.

Each tool is three things wired together:

1. An ``async def`` implementation (below).
2. An OpenAI-style schema dict in :data:`TOOLS_SCHEMA` (passed to the model as ``tools=``).
3. An entry in :data:`TOOL_REGISTRY` (name → callable) the agent loop dispatches on.

**The cardinal rule:** a tool never raises. On failure it returns a descriptive string
beginning with ``"Error:"`` so the model can read what went wrong and recover. Blocking
I/O (file reads, subprocess) is wrapped in :func:`asyncio.to_thread` so it doesn't stall
the event loop while other tools run concurrently.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

# Caps that keep tool output from blowing the context window.
BASH_TIMEOUT = 30
BASH_OUTPUT_LIMIT = 10_000
FIND_LIMIT = 200


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, {len(text) - limit} more chars]"


# ── read_file ────────────────────────────────────────────────────────────────


async def read_file(path: str, offset: int = 0, limit: int = 2000) -> str:
    """Read a file, optionally a window of ``limit`` lines starting at ``offset``."""

    def _read() -> str:
        try:
            lines = Path(path).read_text().splitlines()
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except IsADirectoryError:
            return f"Error: {path} is a directory, not a file"
        except Exception as e:  # pragma: no cover - defensive
            return f"Error reading {path}: {e}"
        window = lines[offset : offset + limit]
        return "\n".join(window)

    return await asyncio.to_thread(_read)


# ── write_file ───────────────────────────────────────────────────────────────


async def write_file(path: str, content: str) -> str:
    """Create or overwrite a file, making parent directories as needed."""

    def _write() -> str:
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            return f"Wrote {len(content)} chars to {path}"
        except Exception as e:
            return f"Error writing {path}: {e}"

    return await asyncio.to_thread(_write)


# ── edit_file ────────────────────────────────────────────────────────────────


async def edit_file(path: str, old_string: str, new_string: str) -> str:
    """Replace the unique occurrence of ``old_string`` with ``new_string``."""

    def _edit() -> str:
        try:
            p = Path(path)
            text = p.read_text()
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except Exception as e:
            return f"Error reading {path}: {e}"

        count = text.count(old_string)
        if count == 0:
            return f"Error: old_string not found in {path}"
        if count > 1:
            return (
                f"Error: old_string is not unique in {path} ({count} matches). "
                "Include more surrounding context to make it unique."
            )
        try:
            p.write_text(text.replace(old_string, new_string))
        except Exception as e:
            return f"Error writing {path}: {e}"
        return f"Edited {path}"

    return await asyncio.to_thread(_edit)


# ── bash ─────────────────────────────────────────────────────────────────────


async def bash(command: str) -> str:
    """Run a shell command and return its combined output plus exit code."""

    def _run() -> str:
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=BASH_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return f"Error: command timed out after {BASH_TIMEOUT}s"
        except Exception as e:
            return f"Error running command: {e}"
        out = proc.stdout
        if proc.stderr:
            out += ("\n" if out else "") + proc.stderr
        out = _truncate(out, BASH_OUTPUT_LIMIT)
        return f"(exit code {proc.returncode})\n{out}".rstrip()

    return await asyncio.to_thread(_run)


# ── grep ─────────────────────────────────────────────────────────────────────


async def grep(pattern: str, path: str = ".") -> str:
    """Recursively search for ``pattern`` and return matches with line numbers."""

    def _grep() -> str:
        try:
            proc = subprocess.run(
                ["grep", "-r", "-n", pattern, path],
                capture_output=True,
                text=True,
                timeout=BASH_TIMEOUT,
            )
        except Exception as e:
            return f"Error running grep: {e}"
        if proc.returncode == 1:
            return f"No matches for {pattern!r} in {path}"
        if proc.returncode > 1:
            return f"Error: grep failed: {proc.stderr.strip()}"
        return _truncate(proc.stdout, BASH_OUTPUT_LIMIT)

    return await asyncio.to_thread(_grep)


# ── find_files ───────────────────────────────────────────────────────────────


async def find_files(pattern: str, path: str = ".") -> str:
    """Find files by name pattern (glob), capped at :data:`FIND_LIMIT` results."""

    def _find() -> str:
        try:
            proc = subprocess.run(
                ["find", path, "-name", pattern],
                capture_output=True,
                text=True,
                timeout=BASH_TIMEOUT,
            )
        except Exception as e:
            return f"Error running find: {e}"
        if proc.returncode != 0 and proc.stderr:
            return f"Error: find failed: {proc.stderr.strip()}"
        matches = [m for m in proc.stdout.splitlines() if m]
        if not matches:
            return f"No files matching {pattern!r} under {path}"
        clipped = matches[:FIND_LIMIT]
        suffix = "" if len(matches) <= FIND_LIMIT else f"\n... [{len(matches) - FIND_LIMIT} more]"
        return "\n".join(clipped) + suffix

    return await asyncio.to_thread(_find)


# ── list_dir ─────────────────────────────────────────────────────────────────


async def list_dir(path: str = ".") -> str:
    """List a directory; directories get a trailing ``/``, files show their size."""

    def _list() -> str:
        try:
            entries = sorted(os.listdir(path))
        except FileNotFoundError:
            return f"Error: directory not found: {path}"
        except NotADirectoryError:
            return f"Error: {path} is not a directory"
        except Exception as e:
            return f"Error listing {path}: {e}"
        if not entries:
            return f"(empty directory: {path})"
        rows = []
        for name in entries:
            full = os.path.join(path, name)
            if os.path.isdir(full):
                rows.append(f"{name}/")
            else:
                try:
                    size = os.path.getsize(full)
                    rows.append(f"{name} ({size} bytes)")
                except OSError:
                    rows.append(name)
        return "\n".join(rows)

    return await asyncio.to_thread(_list)


# ── schemas + registry ───────────────────────────────────────────────────────

TOOLS_SCHEMA: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file. Use offset/limit for large files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"},
                    "offset": {"type": "integer", "description": "Line to start from (0-indexed)", "default": 0},
                    "limit": {"type": "integer", "description": "Max lines to return", "default": 2000},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file with new content. Makes parent dirs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "Full file content"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace a unique occurrence of old_string with new_string in a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to edit"},
                    "old_string": {"type": "string", "description": "Exact text to replace (must be unique)"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute a shell command (ls, git, grep, pytest, etc.) and return its output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Recursively search for a text pattern, returning matches with line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Pattern to search for"},
                    "path": {"type": "string", "description": "Directory or file to search", "default": "."},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_files",
            "description": "Find files by name pattern (glob), e.g. '*.py'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Name pattern, e.g. '*.py'"},
                    "path": {"type": "string", "description": "Directory to search under", "default": "."},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List the contents of a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory to list", "default": "."},
                },
                "required": [],
            },
        },
    },
]

TOOL_REGISTRY = {
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "bash": bash,
    "grep": grep,
    "find_files": find_files,
    "list_dir": list_dir,
}
```

### Design notes

**Why three things per tool?** The async function is what runs. The schema is what the model sees when deciding whether and how to call a tool. The registry entry is what the loop looks up at dispatch time. All three must stay in sync — the test at the end of `test_tools.py` enforces it.

**The caps.** `BASH_TIMEOUT = 30` prevents a runaway command from hanging the loop indefinitely. `BASH_OUTPUT_LIMIT = 10_000` and `FIND_LIMIT = 200` prevent a single tool result from filling the context window. The `_truncate` helper appends a count of elided characters so the model knows output was clipped.

**`edit_file` uniqueness.** If `old_string` appears more than once, a blind `str.replace` would change the wrong site. The count check turns that silent corruption into a visible error: the model gets told to include more surrounding context. This is the right failure mode — informative, recoverable.

**`asyncio.to_thread`.** Every blocking inner function (`_read`, `_write`, `_edit`, `_run`, `_grep`, `_find`, `_list`) is wrapped in `asyncio.to_thread` before being awaited. This hands the blocking call to a thread-pool worker, freeing the event loop to do other work — in particular to run other tool calls in parallel (covered in [Phase 7](./07-parallel-tools.md)).

## Test it

Write the tests first, run them, watch them fail (because the new tools don't exist yet), then add the implementations above.

Add this to `tests/test_tools.py`:

```python
import asyncio
import tools


def run(coro):
    return asyncio.run(coro)


# ── read_file: missing file returns an error string, does not raise ───────────


def test_read_file_missing_returns_error_not_raise():
    out = run(tools.read_file("/no/such/file.txt"))
    assert "Error" in out  # string, not exception


def test_read_file_returns_contents(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("line1\nline2\nline3\n")
    out = run(tools.read_file(str(f)))
    assert "line1" in out and "line3" in out


def test_read_file_offset_and_limit(tmp_path):
    f = tmp_path / "nums.txt"
    f.write_text("\n".join(str(i) for i in range(10)) + "\n")
    out = run(tools.read_file(str(f), offset=2, limit=3))
    assert out.splitlines() == ["2", "3", "4"]


# ── write_file ───────────────────────────────────────────────────────────────


def test_write_file_creates_parent_dirs(tmp_path):
    target = tmp_path / "a" / "b" / "c.txt"
    out = run(tools.write_file(str(target), "payload"))
    assert target.read_text() == "payload"
    assert "c.txt" in out


# ── edit_file ────────────────────────────────────────────────────────────────


def test_edit_file_replaces_unique_string(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("x = 1\ny = 2\n")
    run(tools.edit_file(str(f), "y = 2", "y = 3"))
    assert f.read_text() == "x = 1\ny = 3\n"


def test_edit_file_errors_when_not_found(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("x = 1\n")
    out = run(tools.edit_file(str(f), "not present", "z"))
    assert "Error" in out


def test_edit_file_errors_when_not_unique(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("a\na\n")
    out = run(tools.edit_file(str(f), "a", "b"))
    assert "unique" in out.lower() or "Error" in out


# ── bash ─────────────────────────────────────────────────────────────────────


def test_bash_runs_command():
    out = run(tools.bash("echo hello-from-bash"))
    assert "hello-from-bash" in out


def test_bash_reports_exit_code():
    out = run(tools.bash("exit 3"))
    assert "3" in out


# ── registry / schema wiring ─────────────────────────────────────────────────


def test_registry_matches_schema():
    schema_names = {t["function"]["name"] for t in tools.TOOLS_SCHEMA}
    assert schema_names == set(tools.TOOL_REGISTRY)
    assert len(tools.TOOL_REGISTRY) == 7
```

The key tests to notice:

- `test_read_file_missing_returns_error_not_raise` — proves the cardinal contract. Call with a path that doesn't exist. No `pytest.raises`, no `try/except` in the test. The tool must return a string.
- `test_edit_file_errors_when_not_unique` — proves the uniqueness guard. The model would otherwise silently corrupt two locations at once.
- `test_registry_matches_schema` — a structural invariant: `TOOL_REGISTRY` and `TOOLS_SCHEMA` must name exactly the same 7 tools.

Run:

```bash
uv run pytest tests/test_tools.py -v
```

Expected output (all green):

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
```

### Behavior (BDD)

Verify this phase as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Feature: The toolbox and the never-raise contract
  Every tool returns a string on success or failure — it never raises.
  The registry and schema stay in sync at exactly 7 entries.

  Scenario: a missing-file read returns an error string and the loop continues
    Given a scripted model that calls read_file on "/no/such/file.txt"
    And the scripted model will then return a plain-text final answer
    When run_agent runs
    Then the tool result message for "read_file" contains "Error"
    And the tool result message is role "tool", not a Python exception
    And the model receives a second turn and produces a final answer

  Scenario: edit_file refuses a non-unique old_string with an error result
    Given a file "dup.py" whose content contains the line "x = 1" twice
    And a scripted model that calls edit_file with old_string "x = 1" on that file
    And the scripted model will then return a plain-text final answer
    When run_agent runs
    Then the tool result message for "edit_file" contains "unique"
    And the tool result message for "edit_file" contains "Error"
    And the file "dup.py" is unchanged (no edit was applied)

  Scenario: bash output over the cap is truncated but still returned with the exit code
    Given a scripted model that calls bash with a command that produces more than 10000 chars of output
    And the scripted model will then return a plain-text final answer
    When run_agent runs
    Then the tool result message for "bash" contains "truncated"
    And the tool result message for "bash" contains "exit code"
    And the tool result message for "bash" is a non-empty string (not a Python exception)

  Scenario: the registry and TOOLS_SCHEMA expose exactly the 7 tools
    Given the tools module is imported
    When the TOOL_REGISTRY and TOOLS_SCHEMA are inspected
    Then TOOL_REGISTRY contains exactly the keys "read_file", "write_file", "edit_file", "bash", "grep", "find_files", "list_dir"
    And TOOLS_SCHEMA contains exactly 7 entries
    And every name in TOOLS_SCHEMA matches a key in TOOL_REGISTRY
```

Run this as an integration scenario with the [BDD framework](../guides/bdd-integration-testing.md) — `pytest-bdd` over the `ScriptedLLM` harness from Phase 9. The unit test above proves the mechanism; this scenario specifies the *behavior*.

## Run it

Ask the agent to use two of the new tools in one task:

```bash
uv run main.py "List the files in the src/ directory, then write a file called /tmp/hello.txt containing the word hello"
```

Expected output (abridged):

```
▸ list_dir
  [executing list_dir {'path': 'src/'}]
  [✓ list_dir: 142 chars]
▸ write_file
  [executing write_file {'path': '/tmp/hello.txt', 'content': 'hello'}]
  [✓ write_file: 31 chars]

Done. Listed src/ and wrote /tmp/hello.txt.
```

Verify the write:

```bash
cat /tmp/hello.txt
# hello
```

:::tip
If the model chooses to call both tools in a single turn (two tool calls in one response), you'll see both `▸` lines before either `[executing ...]` line — that's parallel execution kicking in early. [Phase 7](./07-parallel-tools.md) makes this explicit.
:::

:::tip Architecture pattern
This phase's `TOOL_REGISTRY` is already a lightweight [Plugin Architecture](../architecture-patterns/plugin-architecture.md) — formalize it to add GitHub/Jira/Slack/K8s tools without touching the agent core. Reifying each tool call as a [Command](../architecture-patterns/command-pattern.md) object then buys logging, replay, approvals, and undo.
:::

## Recap

You now have a complete toolbox: seven tools, each an async function behind a JSON schema, all registered in `TOOL_REGISTRY`. The cardinal contract — tools return error strings, they never raise — is enforced by tests and lets the model recover from failures gracefully. The caps (`BASH_TIMEOUT`, `BASH_OUTPUT_LIMIT`, `FIND_LIMIT`) and the `edit_file` uniqueness guard are small details that matter at the boundary where code meets reality.

The natural next question is: if the model requests two tools in the same turn, do they run one after the other or at the same time? That's [Phase 7 — Parallel Tool Execution](./07-parallel-tools.md).

For a full reference on the seven built-in tools and their schemas, see [tools/built-in-tools.md](../tools/built-in-tools.md). For a deeper explanation of the never-raise contract and how `is_error` flows back to the model, see [tools/error-handling.md](../tools/error-handling.md).
