"""The system prompt builder.

Built per-run rather than stored as a static constant so it can fold in the live working
directory and date. The tool list here must stay in sync with ``tools.TOOL_REGISTRY``.
"""

from __future__ import annotations

import os
from datetime import date

from skills import ACTIVE_SKILLS, SKILLS, skills_menu


def build_system_prompt(
    cwd: str | None = None,
    extra: str = "",
    skills: list[str] | None = None,
) -> str:
    cwd = cwd or os.getcwd()
    today = date.today().isoformat()

    # Resolve the active skill set: an explicit list (e.g. from the --skills
    # flag) overrides the env-driven ACTIVE_SKILLS default. An empty list means
    # "no skills" — a bare prompt. Unknown names are silently skipped.
    active = skills if skills is not None else ACTIVE_SKILLS
    skill_blocks = "\n".join(SKILLS[s] for s in active if s in SKILLS)

    # Spec-compliant Agent Skills: one cheap menu line per discovered SKILL.md
    # folder. The model calls load_skill to pull a full body in on demand.
    menu = skills_menu()

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
- load_skill: Load the full instructions of a skill listed in the skills menu
{skill_blocks}

{menu}

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
