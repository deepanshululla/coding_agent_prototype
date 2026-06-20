---
sidebar_position: 3
title: "Layer 13.3 — Skills"
description: Compose the agent's behavior from named instruction blocks selected by AGENT_SKILLS, without editing the core prompt.
---

# Layer 13.3 — Skills

:::note Starting point
Layer 13.2 complete: `extra` carries project instructions plus an optional per-session override; `beforeToolCall`/`afterToolCall` hooks are wired in. The test suite passes.
:::

`build_system_prompt` currently has one monolithic guidelines block. That works until you want different modes: a TDD-focused session, a security-audit session, a quick-summarization session. Editing the prompt each time is fragile — you risk breaking something else, and the change isn't version-controlled as a named unit.

Skills solve this. A skill is a named block of Markdown instructions that you compose into the system prompt by name. The active set is controlled by the `AGENT_SKILLS` environment variable or a `--skills` CLI flag. Add a skill, activate it, and the agent's behavior changes — without touching the core loop or the prompt template.

The full design — dict-based registry, file-based skills, env-var configuration, and CLI flags — is in [Skills](../../customization/skills.md).

## What you'll learn

- The skills dict-registry pattern and why named blocks beat an ever-growing monolithic prompt.
- How `AGENT_SKILLS` controls which blocks are active per session.
- How to pass skills through `build_system_prompt` via the `skills` parameter.
- Confirming that deactivated skills are absent from the prompt.

## Build it

### Step 1 — Create `src/skills.py`

Define the skill registry and the helper that reads the active set from the environment:

```python
# src/skills.py
"""Named instruction blocks composed into the system prompt."""

from __future__ import annotations

import os

SKILLS: dict[str, str] = {
    "tdd": """
## Test-driven development
- Write a failing test before adding any new code.
- Run `uv run pytest` to confirm the test fails for the right reason.
- Write the minimum code to make it pass, then refactor.
- Never skip the failing-test step, even for "simple" changes.
""",
    "git": """
## Git workflow
- Before committing, run `git diff --staged` to review what's staged.
- Write commit messages in the imperative mood: "Add X", not "Added X".
- Never commit `.env` files, credentials, or generated build artifacts.
- Stage specific files with `git add <file>`, never `git add -A`.
""",
    "explain": """
## Explanation mode
- Walk through code section by section, not all at once.
- Use concrete examples with actual values, not abstract descriptions.
- Point out non-obvious decisions and the tradeoffs they encode.
- Keep explanations prose-first; use code blocks only for illustrative snippets.
""",
    "security": """
## Security review mode
- Look for injection risks: shell, SQL, path traversal, prompt injection.
- Flag any hardcoded secrets, tokens, or credentials.
- Check that file writes are scoped to the working directory.
- Note trust boundaries: what input is user-controlled vs. system-controlled.
""",
}

DEFAULT_SKILLS: list[str] = ["tdd", "git"]

_env = os.environ.get("AGENT_SKILLS", "")
ACTIVE_SKILLS: list[str] = (
    [s.strip() for s in _env.split(",") if s.strip()]
    if _env
    else DEFAULT_SKILLS
)
```

### Step 2 — Extend `build_system_prompt` to accept skills

Add an optional `skills` parameter. When supplied it overrides `ACTIVE_SKILLS`; when `None` it falls back to the env-driven default:

```python
# src/prompts.py (updated)
from __future__ import annotations

import os
from datetime import date

from skills import SKILLS, ACTIVE_SKILLS


def build_system_prompt(
    cwd: str | None = None,
    extra: str = "",
    skills: list[str] | None = None,
) -> str:
    cwd = cwd or os.getcwd()
    today = date.today().isoformat()
    active = skills if skills is not None else ACTIVE_SKILLS

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

### Step 3 — Expose a `--skills` flag in `main.py`

```python
# main.py (updated)
import argparse
import asyncio
import os

from src.agent import run_agent
from src.prompts import build_system_prompt
from src.project_instructions import load_project_instructions
from src.skills import ACTIVE_SKILLS


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

    cwd = os.getcwd()
    session_override = os.environ.get("AGENT_SESSION_CONTEXT", "")
    extra = "\n\n".join(filter(None, [
        load_project_instructions(cwd),
        session_override,
    ]))

    system_prompt = build_system_prompt(cwd=cwd, extra=extra, skills=active)
    await run_agent(task, system_prompt=system_prompt)


if __name__ == "__main__":
    asyncio.run(main())
```

:::tip Skill precedence
CLI `--skills` beats `AGENT_SKILLS` env var, which beats `DEFAULT_SKILLS`. An empty `--skills` flag (`uv run main.py --skills "list this repo"`) activates zero skills — a bare prompt with no extra instruction blocks.
:::

## Test it

### Behavior (BDD)

Verify this layer as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Scenario: Active skill appears in the prompt; deactivated skill does not
  Given AGENT_SKILLS is set to "tdd"
  When build_system_prompt is called with skills=["tdd"]
  Then the returned prompt contains "Write a failing test before adding any new code"
  And the returned prompt does not contain "Walk through code section by section"
  When build_system_prompt is called with skills=["explain"]
  Then the returned prompt contains "Walk through code section by section"
  And the returned prompt does not contain "Write a failing test before adding any new code"
```

Run this as an integration scenario with the [BDD framework](../../guides/bdd-integration-testing.md).

The scenario fails before the change because `build_system_prompt` ignores `skills` and the monolithic prompt always includes the same text. After the change, only active skills appear.

### Existing tests

```bash
uv run pytest -q
```

`build_system_prompt` gains a new optional parameter; callers that don't pass it still get the `ACTIVE_SKILLS` default. No existing call site changes.

## Run it

```bash
# Default: AGENT_SKILLS env var (or tdd,git if unset)
uv run main.py "add a new grep_lines function to tools.py"

# Only security review for this session
AGENT_SKILLS=security uv run main.py "audit src/agent.py for injection risks"

# Override via CLI flag
uv run main.py --skills explain "walk me through how the streaming loop works"

# No skills: bare prompt
uv run main.py --skills "summarize this repo in one paragraph"
```

:::tip Architecture pattern
Selecting a skill set per task is the [Strategy](../../architecture-patterns/strategy-pattern.md) pattern — different behavior for different task types.
:::

## Recap

`src/skills.py` holds named instruction blocks in a dict. `build_system_prompt` accepts a `skills` list that selects which blocks to inject. `AGENT_SKILLS` controls the default; `--skills` overrides per invocation. Active skills appear in the prompt; deactivated ones don't.

The next layer takes skills further: the open `SKILL.md` standard — portable, installable skill folders that the agent discovers at startup and loads on demand.

→ [Layer 13.4 — Agent Skills (Install & Read)](./4-agent-skills.md)
