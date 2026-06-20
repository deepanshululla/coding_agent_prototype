---
sidebar_position: 1
title: Prompt Templates
description: How to customize the system prompt in build_system_prompt — injecting context, swapping guidelines, and keeping the tool list accurate.
---

# Prompt Templates

The system prompt is the single biggest lever you have over your agent's behavior. Everything the model "knows" about its role, its tools, and your project comes from this string. This page explains how `build_system_prompt` works, how to extend it, and how to avoid the most common pitfalls.

## How `build_system_prompt` works

`src/prompts.py` exports one function:

```python
def build_system_prompt(cwd: str | None = None, extra: str = "") -> str:
    cwd = cwd or os.getcwd()
    today = date.today().isoformat()
    return f"""You are an expert coding assistant ..."""
```

It has two moving parts at runtime:

| Part | How it's filled |
|------|-----------------|
| `{cwd}` | Defaults to `os.getcwd()` — the directory where `main.py` is invoked |
| `{today}` | `date.today().isoformat()` — injected fresh each call |
| `{extra}` | Caller-supplied string, appended at the end of the prompt |

Everything else — the role description, tool list, and guidelines — is a static template string baked into the function body.

:::note
The snippet below reflects the shipped `src/prompts.py`.
:::

## The `extra` parameter

`extra` is a clean escape hatch. Pass any string and it lands at the bottom of the prompt, after the static sections:

```python
from src.prompts import build_system_prompt

# Add a one-liner instruction for a specific session
prompt = build_system_prompt(
    extra="This codebase uses strict type hints. Always annotate return types."
)
```

You can pass multi-line strings. The agent sees them as a continuation of its instructions:

```python
extra = """
## Project conventions
- All async functions must use `await asyncio.to_thread(...)` for blocking I/O.
- Tests live in `tests/` and are run with `uv run pytest`.
- Never commit `.env` files.
"""
prompt = build_system_prompt(extra=extra)
```

`extra` is intentionally unstructured. Use any format that makes sense — Markdown headers work well because the model is trained to treat them as semantic sections.

## Swapping the guidelines section

The "Guidelines" block inside the prompt currently looks like this:

```
## Guidelines
- Start by understanding the task. Use read_file or list_dir to explore before making changes.
- Prefer targeted edits (edit_file) over full rewrites (write_file) for existing files.
- Always verify changes with bash (e.g., run tests, check syntax) after editing.
- When a tool returns an error, reason about it and try an alternative approach.
- Be concise in your text responses. Let the tools do the work.
```

To change the guidelines, edit the template string in `src/prompts.py` directly. There is no plugin system for this in v1 — it is a plain Python f-string. That simplicity is a feature: the prompt is always grep-able and diff-able.

If you want to support multiple guideline sets (e.g., a "careful" mode vs. a "fast" mode), the cleanest approach is to parametrize `build_system_prompt`:

```python
GUIDELINES = {
    "default": """
## Guidelines
- Start by understanding the task...
""",
    "careful": """
## Guidelines
- Read every file referenced before making any change.
- Write a test before editing code.
- Run `uv run pytest` and confirm green before reporting done.
""",
}

def build_system_prompt(cwd=None, extra="", mode="default") -> str:
    cwd = cwd or os.getcwd()
    today = date.today().isoformat()
    guidelines = GUIDELINES[mode]
    return f"""...\n{guidelines}\n...\n{extra}"""
```

Pass `mode="careful"` from `main.py` or from a flag on the CLI.

## Project-specific instructions — the CLAUDE.md / AGENTS.md convention

Claude Code, Cursor, and Codex all support a convention where a file at the repo root (`CLAUDE.md`, `AGENTS.md`, `.cursorrules`) is automatically loaded and injected into the system prompt. You can implement the same pattern:

```python
import os
from pathlib import Path

_CONVENTION_FILES = ["CLAUDE.md", "AGENTS.md", ".cursorrules"]

def _load_project_instructions(cwd: str) -> str:
    for name in _CONVENTION_FILES:
        p = Path(cwd) / name
        if p.exists():
            content = p.read_text(encoding="utf-8").strip()
            return f"\n## Project instructions (from {name})\n\n{content}\n"
    return ""

def build_system_prompt(cwd: str | None = None, extra: str = "") -> str:
    cwd = cwd or os.getcwd()
    today = date.today().isoformat()
    project_instructions = _load_project_instructions(cwd)
    return f"""...\n{project_instructions}\n{extra}"""
```

With this in place, every project that already has a `CLAUDE.md` gets its conventions applied automatically, without touching `prompts.py`.

:::tip
Keep `CLAUDE.md` under version control. That way project instructions travel with the code and are reviewed in PRs.
:::

## Keeping the tool list accurate

The "Available Tools" section in the prompt is a hand-written list. If you add or remove a tool from `src/tools.py`, you must update the prompt manually. That's easy to forget.

A reliable pattern is to generate the tool section from `TOOLS_SCHEMA` itself:

```python
from src.tools import TOOLS_SCHEMA

def _tool_list_section() -> str:
    lines = ["## Available Tools"]
    for entry in TOOLS_SCHEMA:
        fn = entry["function"]
        lines.append(f"- `{fn['name']}`: {fn['description']}")
    return "\n".join(lines)
```

Now `build_system_prompt` calls `_tool_list_section()` instead of embedding a static list. Add a tool to `TOOLS_SCHEMA`, and the prompt updates automatically.

:::warning
The generated list is only as good as the `description` field in each schema entry. Write clear, imperative descriptions in `TOOLS_SCHEMA` — they appear verbatim in the model's instructions.
:::

## Injecting repo context

Giving the model a snapshot of the repo structure at startup saves it from an exploratory `list_dir` call on almost every task. This is especially useful on large repos where the model might otherwise thrash:

```python
import subprocess

def _repo_snapshot(cwd: str, max_lines: int = 80) -> str:
    result = subprocess.run(
        ["find", ".", "-not", "-path", "./.git/*", "-not", "-path", "./node_modules/*",
         "-type", "f", "-name", "*.py"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=5,
    )
    lines = result.stdout.strip().splitlines()[:max_lines]
    listing = "\n".join(lines)
    return f"\n## Repo snapshot (Python files)\n```\n{listing}\n```\n"

def build_system_prompt(cwd: str | None = None, extra: str = "") -> str:
    cwd = cwd or os.getcwd()
    snapshot = _repo_snapshot(cwd)
    # ... rest of the prompt
```

Keep snapshots short. The model does not need the full tree; it needs enough to orient itself. 80 lines is usually plenty. If context length is a concern, see [compaction](../advanced/compaction.md).

## Full example: repo-aware prompt builder

Putting it together:

```python
import os
import subprocess
from datetime import date
from pathlib import Path
from src.tools import TOOLS_SCHEMA

_CONVENTION_FILES = ["CLAUDE.md", "AGENTS.md", ".cursorrules"]

def _load_project_instructions(cwd: str) -> str:
    for name in _CONVENTION_FILES:
        p = Path(cwd) / name
        if p.exists():
            content = p.read_text(encoding="utf-8").strip()
            return f"\n## Project instructions (from {name})\n\n{content}\n"
    return ""

def _tool_list_section() -> str:
    lines = ["## Available Tools"]
    for entry in TOOLS_SCHEMA:
        fn = entry["function"]
        lines.append(f"- `{fn['name']}`: {fn['description']}")
    return "\n".join(lines)

def build_system_prompt(cwd: str | None = None, extra: str = "") -> str:
    cwd = cwd or os.getcwd()
    today = date.today().isoformat()
    tools_section = _tool_list_section()
    project_instructions = _load_project_instructions(cwd)

    return f"""You are an expert coding assistant running inside a terminal agent harness.
You help users by reading files, executing shell commands, editing code, and writing new files.

{tools_section}

## Guidelines
- Start by understanding the task. Use read_file or list_dir to explore before making changes.
- Prefer targeted edits (edit_file) over full rewrites (write_file) for existing files.
- Always verify changes with bash (e.g., run tests, check syntax) after editing.
- When a tool returns an error, reason about it and try an alternative approach.
- Be concise in your text responses. Let the tools do the work.

## Environment
Working directory: {cwd}
Today's date: {today}
{project_instructions}
{extra}"""
```

## Related pages

- [Custom Models](./custom-models.md) — change the model without touching the prompt
- [Skills](./skills.md) — how to grow toward reusable instruction snippets
- [The Agent Loop](../architecture/the-agent-loop.md) — where `build_system_prompt` is called
