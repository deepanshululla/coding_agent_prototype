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
