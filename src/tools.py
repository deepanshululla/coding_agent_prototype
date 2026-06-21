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
import base64
import contextvars
import json
import os
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path

# config is imported as a module (not `from config import …`) for values read at
# call time — CODE_MODEL can be flipped per-run, so write_code consults it live.
import config

# Caps that keep tool output from blowing the context window. Resolved values
# (defaults + AGENT_* overrides) live in config.py — the single source of truth.
from config import BASH_OUTPUT_LIMIT, BASH_TIMEOUT, FIND_LIMIT, READ_LIMIT

# Image file extensions that trigger base64 encoding instead of text read
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".svg"}


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, {len(text) - limit} more chars]"


# ── read_file ────────────────────────────────────────────────────────────────


async def read_file(path: str, offset: int = 0, limit: int = READ_LIMIT) -> str:
    """Read a file, optionally a window of ``limit`` lines starting at ``offset``.

    Image files (detected by extension) are returned as a JSON string containing
    base64-encoded data: {"type": "image", "format": "png", "data": "base64..."}.
    Text files are returned as plain text.
    """

    def _read() -> str:
        p = Path(path)

        # Check if file exists first
        try:
            if not p.exists():
                return f"Error: file not found: {path}"
            if p.is_dir():
                return f"Error: {path} is a directory, not a file"
        except Exception as e:  # pragma: no cover - defensive
            return f"Error checking {path}: {e}"

        # Image files: return base64-encoded JSON
        if p.suffix.lower() in IMAGE_EXTENSIONS:
            try:
                img_bytes = p.read_bytes()
                b64_data = base64.b64encode(img_bytes).decode("ascii")
                # Strip the leading dot from suffix for format field
                fmt = p.suffix.lower()[1:]  # .png -> png
                return json.dumps(
                    {"type": "image", "format": fmt, "data": b64_data}, separators=(",", ":")
                )
            except Exception as e:
                return f"Error reading image {path}: {e}"

        # Text files: return plain text (original behavior)
        try:
            lines = p.read_text().splitlines()
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except IsADirectoryError:
            return f"Error: {path} is a directory, not a file"
        except Exception as e:
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


# ── load_skill ───────────────────────────────────────────────────────────────


async def load_skill(name: str) -> str:
    """Return the full instruction body of an installed skill by name."""
    # Imported lazily so tools.py stays importable even if skills discovery
    # has heavier deps, and to rescan freshly on each call.
    from skills import discover_skills

    skill = discover_skills().get(name)
    if skill is None:
        return f"Error: no installed skill named {name!r}"
    return skill.body


async def save_memory(name: str, description: str, type: str, content: str) -> str:
    """Save a memory to the project-specific memory directory.

    Args:
        name: Kebab-case slug (e.g. "user-role", "feedback-testing")
        description: One-line summary
        type: One of: user, feedback, project, reference
        content: Markdown body content

    Returns success message or validation error.
    """
    import asyncio
    from datetime import UTC, datetime

    import memory

    VALID_TYPES = {"user", "feedback", "project", "reference"}
    if type not in VALID_TYPES:
        return f"Error: type must be one of {VALID_TYPES}, got {type!r}"

    if not name or not description or not content:
        return "Error: name, description, and content are required"

    def _save():
        mem_dir = memory.get_project_memory_dir(os.getcwd())

        # Check if memory already exists to preserve created timestamp
        mem_path = mem_dir / f"{name}.md"
        existing = None
        if mem_path.exists():
            try:
                existing = memory.parse_memory_file(mem_path)
            except Exception:
                pass

        from types_ import Memory

        now = datetime.now(UTC).isoformat()
        mem = Memory(
            name=name,
            description=description,
            type=type,
            content=content,
            created=existing.created if existing else now,
            updated=now,
        )
        memory.save_memory_file(mem, mem_dir)
        return f"Saved memory: {name}"

    return await asyncio.to_thread(_save)


async def list_memories() -> str:
    """List all memories in the project-specific memory directory.

    Returns a formatted list of memories with their descriptions.
    """
    import asyncio

    import memory

    def _list():
        mem_dir = memory.get_project_memory_dir(os.getcwd())
        if not mem_dir.exists():
            return "No memories saved yet."

        memories = memory.load_all_memories(mem_dir)
        if not memories:
            return "No memories saved yet."

        lines = ["## Project Memories", ""]
        for mem in memories:
            lines.append(f"- **{mem.name}** ({mem.type}): {mem.description}")
        return "\n".join(lines)

    return await asyncio.to_thread(_list)


# ── write_code (dual-model delegation, ADR-0015) ──────────────────────────────

# True while a write_code sub-agent is running, so a nested write_code call (the
# coding model trying to delegate to itself) is refused instead of recursing.
# A ContextVar, not a plain flag, so the value propagates into the gathered tool
# tasks of the sub-agent's own loop (asyncio.gather copies the current context).
_in_write_code: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_in_write_code", default=False
)

# Focused brief for the coding sub-agent. It is the specialist that actually
# edits files, so it gets no delegation nudge of its own (delegate_coding=False)
# — just a clear "implement, verify, summarize" loop.
_CODE_AGENT_BRIEF = (
    "You are a focused coding specialist. A reasoning agent has delegated a "
    "concrete code change to you. Implement it directly: read the relevant "
    "files, make targeted edits (prefer edit_file over rewrites), and verify "
    "with bash where reasonable. Do not ask questions — make your best change. "
    "End with a 1-3 sentence summary naming the files you changed and what you "
    "did, so the calling agent can continue."
)


def _final_assistant_text(history: list[dict]) -> str:
    """The sub-agent's answer: last assistant message with plain-string content."""
    for message in reversed(history):
        if message.get("role") == "assistant" and isinstance(message.get("content"), str):
            return message["content"]
    return ""


async def write_code(instruction: str, context: str = "") -> str:
    """Delegate a concrete coding change to the specialized code model.

    Runs a focused reactive sub-agent on ``config.CODE_MODEL`` (read live) with
    the full file-editing toolset, and returns its summary of what it changed.
    This is the seam that lets a strong reasoning/tool model drive the loop while
    a coding-specialist model does the edits (ADR-0015).

    ``instruction`` is the self-contained change to make; ``context`` is optional
    background (relevant files, constraints) folded into the sub-task. Returns an
    error string (never raises) when delegation is disabled or nested.
    """
    if not config.CODE_MODEL:
        return (
            "Error: write_code is unavailable because AGENT_CODE_MODEL is not set. "
            "Make the edit yourself with edit_file / write_file."
        )
    if _in_write_code.get():
        return (
            "Error: write_code cannot be nested. You are the coding model — "
            "use read_file / edit_file / write_file / bash directly."
        )

    token = _in_write_code.set(True)
    try:
        # Lazy imports: agent imports tools at module load, so importing it at the
        # top would be circular; prompts is cheap but kept lazy for symmetry.
        from agent import run_agent
        from prompts import build_system_prompt

        sub_task = instruction if not context else f"{instruction}\n\nContext:\n{context}"
        system_prompt = build_system_prompt(extra=_CODE_AGENT_BRIEF, delegate_coding=False)
        history = await run_agent(
            sub_task,
            system_prompt=system_prompt,
            model=config.CODE_MODEL,
            architecture="reactive",  # the coder is a plain loop, not nested orchestration
        )
        return _final_assistant_text(history) or "(coding sub-agent finished with no summary)"
    except Exception as e:  # never raise out of a tool
        return f"Error in write_code sub-agent: {e}"
    finally:
        _in_write_code.reset(token)


# ── schemas + registry ───────────────────────────────────────────────────────

_BASE_TOOLS_SCHEMA: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the contents of a file. Image files (.png, .jpg, .jpeg, .gif, .webp, etc.) "
                "are returned as JSON with base64-encoded data. Text files return plain text. "
                "Use offset/limit for large text files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"},
                    "offset": {
                        "type": "integer",
                        "description": "Line to start from (0-indexed, text files only)",
                        "default": 0,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max lines to return (text files only)",
                        "default": 2000,
                    },
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
                    "old_string": {
                        "type": "string",
                        "description": "Exact text to replace (must be unique)",
                    },
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
            "description": (
                "Execute a shell command (ls, git, grep, pytest, etc.) and return its output."
            ),
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
            "description": (
                "Recursively search for a text pattern, returning matches with line numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Pattern to search for"},
                    "path": {
                        "type": "string",
                        "description": "Directory or file to search",
                        "default": ".",
                    },
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
                    "path": {
                        "type": "string",
                        "description": "Directory to search under",
                        "default": ".",
                    },
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
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": (
                "Load the full instruction body of an installed skill. "
                "Call this when you recognize a skill in the skills menu "
                "applies to the current task."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Skill name as listed in the skills menu",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": (
                "Save a memory to the project-specific memory directory. "
                "Memories persist across conversations and are loaded into "
                "the system prompt automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Kebab-case slug (e.g., 'user-role', 'feedback-testing')",
                    },
                    "description": {
                        "type": "string",
                        "description": "One-line summary of what this memory contains",
                    },
                    "type": {
                        "type": "string",
                        "description": (
                            "Memory type: 'user' (about the user), "
                            "'feedback' (how to approach work), "
                            "'project' (ongoing work/goals), "
                            "or 'reference' (external pointers)"
                        ),
                        "enum": ["user", "feedback", "project", "reference"],
                    },
                    "content": {
                        "type": "string",
                        "description": "Markdown body content",
                    },
                },
                "required": ["name", "description", "type", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_memories",
            "description": "List all memories saved in the project-specific memory directory.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]

# Only advertised when a code model is configured (ADR-0015). Kept out of the
# base list so a single-model run sees exactly the tools it always had.
WRITE_CODE_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": "write_code",
        "description": (
            "Delegate a concrete code change to the specialized coding model. "
            "Prefer this over editing files yourself: describe the change you "
            "want in a clear, self-contained instruction and a coding-specialist "
            "sub-agent will read the files, make the edits, and report back what "
            "it changed. Use read_file/grep yourself first to gather the context "
            "the instruction needs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "The self-contained code change to make.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional background: relevant files, constraints, findings.",
                    "default": "",
                },
            },
            "required": ["instruction"],
        },
    },
}


def build_tools_schema(code_model: str | None) -> list[dict]:
    """The tool schema sent to the model, gated on dual-model delegation.

    Appends ``write_code`` only when ``code_model`` is set, so a single-model run
    is byte-for-byte the schema it has always been. Pure function of its argument
    so it is unit-testable without reloading the module under a patched env.
    """
    if code_model:
        return [*_BASE_TOOLS_SCHEMA, WRITE_CODE_SCHEMA]
    return list(_BASE_TOOLS_SCHEMA)


# Resolved once at import from the configured CODE_MODEL (env is set before
# import on the real path). The provider sends this to the model as `tools=`.
TOOLS_SCHEMA: list[dict] = build_tools_schema(config.CODE_MODEL)

# Name → coroutine. The MCP client (Layer 13.5) injects extra entries at runtime
# keyed by dynamic names, so the value type is the broad "any async tool callable"
# rather than the union of the built-ins' exact signatures.
TOOL_REGISTRY: dict[str, Callable[..., Awaitable[str]]] = {
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "bash": bash,
    "grep": grep,
    "find_files": find_files,
    "list_dir": list_dir,
    "load_skill": load_skill,
    "save_memory": save_memory,
    "list_memories": list_memories,
}

# write_code is registered only when a code model is configured — gated in lockstep
# with the schema above so every advertised tool has an implementation and vice
# versa (the registry == schema invariant). It self-guards on CODE_MODEL too, so a
# stale call after the env flips is still answered with a clear error, not a crash.
if config.CODE_MODEL:
    TOOL_REGISTRY["write_code"] = write_code
