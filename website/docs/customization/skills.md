---
sidebar_position: 3
title: Skills
description: How named instruction blocks compose into the system prompt — the skills design, dict-based registry, env-var configuration, CLI flags, and file-based skill authoring.
---

# Skills

A skill is a named block of instructions that gets injected into the system prompt. Instead of one monolithic prompt, you compose the agent's behavior from discrete, independently maintainable units — each skill adds a focused set of behaviors without touching anything else.

The skills system is the project's supported design for making the agent's behavior composable and configurable. The core `build_system_prompt()` in `src/prompts.py` ships today as a single f-string; skills are the recommended extension point for adding, removing, or swapping instruction blocks without editing that core function.

:::note
The core prompt in `src/prompts.py` is a static f-string today. The skills loader described here is the intended architecture for composing it — wire it in by following the steps below. Nothing about the steps requires changing the core agent loop or the tool layer.
:::

## What a skill is

A skill has three things:

- A **name** (`"tdd"`, `"git"`, `"explain"`)
- A **block of text** that extends the system prompt with role-specific instructions
- Optionally, a set of **conditions** under which it applies (e.g., only when certain tools are registered)

The prompt builder walks the active skill list, concatenates the text blocks, and passes the result into `build_system_prompt()` via its `extra` parameter — or directly by extending the returned string. The model then has all active skills in scope simultaneously.

A skill is not a separate agent or a separate API call. It is plain text injected before the environment block. The model interprets it along with everything else in the system prompt.

## Step 1: Define skills in a dict

Pull named instruction blocks into a registry:

```python
# src/skills.py

SKILLS: dict[str, str] = {
    "tdd": """
## Test-driven development
- Write a failing test before adding any code.
- Run `uv run pytest` to confirm the test fails for the right reason.
- Write the minimum code to make it pass, then refactor.
""",
    "git": """
## Git workflow
- Before committing, run `git diff --staged` to review what's staged.
- Write commit messages in the imperative mood: "Add X", not "Added X".
- Never commit `.env` files or credentials.
""",
    "explain": """
## Explanation mode
- When asked to explain code, walk through it section by section.
- Use concrete examples with actual values, not abstract descriptions.
- Point out non-obvious decisions and the tradeoffs they encode.
""",
}

DEFAULT_SKILLS = ["tdd", "git"]
```

Keep each skill's text focused. If a block grows past 20–30 lines, move it to a file (see [Step 5](#step-5-load-skills-from-files-optional)).

## Step 2: Compose skills into the system prompt

Extend `build_system_prompt()` to accept a skill list and inject the matching blocks:

```python
# src/prompts.py
from __future__ import annotations

import os
from datetime import date

from skills import SKILLS, DEFAULT_SKILLS


def build_system_prompt(
    cwd: str | None = None,
    extra: str = "",
    skills: list[str] | None = None,
) -> str:
    cwd = cwd or os.getcwd()
    today = date.today().isoformat()
    active = skills if skills is not None else DEFAULT_SKILLS

    skill_blocks = "\n".join(SKILLS[s] for s in active if s in SKILLS)

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

{skill_blocks}

## Environment
Working directory: {cwd}
Today's date: {today}

{extra}""".rstrip() + "\n"
```

Notice the import is `from skills import SKILLS, DEFAULT_SKILLS` — no `src.` prefix. The project sets `pythonpath = ["src"]` in `pyproject.toml`, so all modules under `src/` are importable directly. See how `src/agent.py` uses `from prompts import build_system_prompt` for the same reason.

## Step 3: Configure via environment variables

The project follows an `AGENT_*` naming scheme for tunable env vars (see [Settings Reference](../operations/settings.md)). Two variables govern the skills system:

| Variable | Default | What it controls |
|---|---|---|
| `AGENT_SKILLS` | `"tdd,git"` | Comma-separated skill names to activate |
| `AGENT_SKILLS_DIR` | `"src/skills"` | Directory of `.md` skill files for file-based skills |

Read them in `src/skills.py`:

```python
# src/skills.py (env-var integration)
import os

_env_skills = os.environ.get("AGENT_SKILLS", "")
ACTIVE_SKILLS: list[str] = (
    [s.strip() for s in _env_skills.split(",") if s.strip()]
    if _env_skills
    else DEFAULT_SKILLS
)

SKILLS_DIR = os.environ.get("AGENT_SKILLS_DIR", "src/skills")
```

Then use `ACTIVE_SKILLS` as the default in `build_system_prompt()`:

```python
active = skills if skills is not None else ACTIVE_SKILLS
```

Usage in the shell:

```bash
# Default — activates tdd and git
uv run main.py "add type hints to tools.py"

# Only the git skill
AGENT_SKILLS=git uv run main.py "clean up uncommitted changes"

# Custom skills directory
AGENT_SKILLS_DIR=~/.config/agent/skills AGENT_SKILLS=tdd,security \
    uv run main.py "audit auth.py for injection risks"

# No skills at all
AGENT_SKILLS="" uv run main.py "summarize this repo in one paragraph"
```

Set `AGENT_SKILLS` and `AGENT_SKILLS_DIR` in `.env` at the repo root for persistent defaults. The file is loaded automatically by `python-dotenv` in `main.py`.

## Step 4: Accept skills from the CLI

Expose a `--skills` flag so skills can be overridden per invocation without changing env vars:

```python
# main.py
import argparse
import asyncio

from agent import run_agent
from prompts import build_system_prompt
from skills import ACTIVE_SKILLS


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", nargs="+")
    parser.add_argument(
        "--skills",
        nargs="*",
        default=None,
        metavar="SKILL",
        help="Skills to activate (space-separated). Overrides AGENT_SKILLS.",
    )
    args = parser.parse_args()

    task = " ".join(args.task)
    active = args.skills if args.skills is not None else ACTIVE_SKILLS
    prompt = build_system_prompt(skills=active)
    await run_agent(task, system_prompt=prompt)


if __name__ == "__main__":
    asyncio.run(main())
```

Examples:

```bash
# Use the environment default (AGENT_SKILLS or ["tdd", "git"])
uv run main.py "add a new grep_lines tool"

# Override to just TDD for this invocation
uv run main.py --skills tdd "add a new grep_lines tool"

# Activate tdd + explain
uv run main.py --skills tdd explain "walk me through tools.py"

# Empty list — bare prompt, no skill blocks
uv run main.py --skills "summarize this repo in one paragraph"
```

CLI flags take precedence over the `AGENT_SKILLS` env var. `AGENT_SKILLS` takes precedence over the `DEFAULT_SKILLS` constant.

## Step 5: Load skills from files (optional)

When skill text grows long, or when you want to edit and version skills independently of Python source, move them to markdown files:

```
src/
  skills/
    tdd.md
    git.md
    explain.md
    security.md
```

Load them with a small helper:

```python
# src/skills.py (file-based loader)
from pathlib import Path

def load_skill(name: str, skills_dir: str | None = None) -> str:
    base = Path(skills_dir or SKILLS_DIR)
    path = base / f"{name}.md"
    if not path.exists():
        raise ValueError(f"Unknown skill: {name!r} (looked in {base})")
    return path.read_text(encoding="utf-8").strip()
```

You can mix the dict and file-based approaches. A merged loader that falls back from files to the dict gives you flexibility during the transition:

```python
def get_skill(name: str, skills_dir: str | None = None) -> str:
    base = Path(skills_dir or SKILLS_DIR)
    path = base / f"{name}.md"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    if name in SKILLS:
        return SKILLS[name].strip()
    raise ValueError(f"Unknown skill: {name!r}")
```

File-based skills are editable in any text editor, versionable in git, and reviewable in PRs — without touching Python source.

## What pi.dev does beyond this

This project's skills system covers the core pattern: text blocks composed into the system prompt. Pi's implementation adds:

- **Tool dependencies** — a skill declares which tools it requires; the builder warns if a required tool isn't registered.
- **Named slash-commands** — skills can expose `/commit`, `/explain`, etc. for interactive invocation.
- **Workspace-level skill directories** — pi reads from a `skills/` folder at the workspace root, separate from the package source.

These are additive layers on top of the same underlying idea. Start with the dict-based approach; add the machinery only when you have a concrete reason for it.

## When a skills system pays off

You'll feel the need for skills when:

1. **You have 5+ distinct modes of behavior** that don't belong in every session — a "security auditor" mode, a "test writer" mode, a "documentation writer" mode.
2. **Different users want different subsets** enabled by default.
3. **Skills need independent versioning** — update the git workflow block without touching TDD instructions.
4. **Third parties register their own skills** — the dict or file-based loader becomes a plugin surface.

For a focused coding agent, the `AGENT_SKILLS` env var and `--skills` CLI flag cover most real needs without building a full plugin registry.

## Related pages

- [Installing Claude Skills](./installing-claude-skills.md) — load portable `SKILL.md` skill folders from Claude Code's ecosystem
- [Prompt Templates](./prompt-templates.md) — the `extra` parameter, `build_system_prompt` API, and per-session overrides
- [Extensions & Hooks](./extensions-and-hooks.md) — hook points that complement skills
- [Settings Reference](../operations/settings.md) — full list of `AGENT_*` environment variables and where to set them
