---
sidebar_position: 1
title: "Layer 13.1 — Project Instructions (AGENTS.md)"
description: Load AGENTS.md / CLAUDE.md from the repo root into the system prompt via build_system_prompt's extra parameter so the agent automatically picks up project-specific conventions.
---

# Layer 13.1 — Project Instructions (AGENTS.md)

:::note Implemented
This step is implemented on branch `step/phase-13-1-project-instructions` (plan: `plans/tutorial/phase-13-1-project-instructions.md`).
:::

:::note Starting point
The hardened agent from Phase 12: `src/agent.py`, `src/tools.py`, `src/provider.py`, `src/prompts.py`, `src/types_.py`, `main.py`, and a passing test suite. The agent runs reliably but has no awareness of project-specific conventions — every repo looks the same to it.
:::

The agent is generic. It knows how to read files and run shell commands, but it doesn't know that *this* project uses `uv run pytest`, or that `.env` files must never be committed, or that `src/types_.py` has a trailing underscore to avoid shadowing stdlib `types`. Without that context, it will rediscover these facts from scratch on every task — or get them wrong entirely.

The solution is a file at the repo root — `AGENTS.md` or `CLAUDE.md` — that states the project's conventions once, in plain Markdown. This layer adds a loader that discovers that file and folds its contents into the system prompt automatically, so the agent walks into every session already briefed.

The full design — discovery order, upward git-root walk, deduplication of symlinked files — is documented in [Project Instructions (AGENTS.md)](../../customization/project-instructions.md). This layer wires the loader into `main.py`.

## What you'll learn

- Why per-project instructions belong in version control alongside the code.
- How `load_project_instructions(cwd)` discovers and concatenates `AGENTS.md` and `CLAUDE.md`.
- How to pass the result into `build_system_prompt` via the `extra` parameter with no changes to the prompt itself.
- The security implication of loading text from a repo you didn't write.

## Build it

### Step 1 — Create `src/project_instructions.py`

The loader walks from the current directory up to the git root, collecting every matching instruction file. Symlinked files are deduplicated by resolved path so a `CLAUDE.md → AGENTS.md` symlink doesn't inject the same content twice.

```python
# src/project_instructions.py
"""Discover and load AGENTS.md / CLAUDE.md instruction files."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_DEFAULT_FILES = ["AGENTS.md", "CLAUDE.md"]


def _git_root(cwd: str) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _candidate_dirs(cwd: str) -> list[Path]:
    """Return [cwd, ..., git_root] — nearest first."""
    start = Path(cwd).resolve()
    root_str = _git_root(cwd)
    root = Path(root_str).resolve() if root_str else start

    dirs: list[Path] = []
    current = start
    while True:
        dirs.append(current)
        if current == root:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return dirs


def load_project_instructions(cwd: str) -> str:
    """
    Discover instruction files in cwd (and parents up to the git root).
    Returns a formatted string for build_system_prompt(extra=...), or "" if none found.
    """
    raw = os.environ.get("AGENT_INSTRUCTIONS_FILES", ",".join(_DEFAULT_FILES))
    names = [n.strip() for n in raw.split(",") if n.strip()]
    if not names:
        return ""

    sections: list[str] = []
    seen: set[Path] = set()

    for search_dir in _candidate_dirs(cwd):
        for name in names:
            p = search_dir / name
            resolved = p.resolve()
            if resolved in seen:
                continue
            if p.exists():
                seen.add(resolved)
                content = p.read_text(encoding="utf-8").strip()
                sections.append(f"## Project instructions (from {name})\n\n{content}")

    return ("\n\n".join(sections) + "\n") if sections else ""
```

Key design choices:

- **All matching files are read**, not just the first. If both exist, both are injected under distinct headers.
- **Walk toward the git root** so running the agent from a subdirectory still picks up root-level instructions.
- **`AGENT_INSTRUCTIONS_FILES`** env var lets you add `.cursorrules` or disable loading entirely (`AGENT_INSTRUCTIONS_FILES=""`).

### Step 2 — Wire it into `main.py`

Pass `load_project_instructions` output as `extra` to `build_system_prompt`. The call site is the only change — nothing inside `build_system_prompt` itself needs to move.

```python
# main.py
import asyncio
import os
import sys

from src.agent import run_agent
from src.prompts import build_system_prompt
from src.project_instructions import load_project_instructions


async def main() -> None:
    task = " ".join(sys.argv[1:]) or input("Task: ")
    cwd = os.getcwd()
    system_prompt = build_system_prompt(
        cwd=cwd,
        extra=load_project_instructions(cwd),
    )
    await run_agent(task, system_prompt=system_prompt)


if __name__ == "__main__":
    asyncio.run(main())
```

If you already have other content going into `extra`, concatenate rather than replace:

```python
extra = "\n\n".join(filter(None, [
    load_project_instructions(cwd),
    session_override,   # any per-session string
]))
system_prompt = build_system_prompt(cwd=cwd, extra=extra)
```

:::warning Security: AGENTS.md is untrusted input
If you run this agent on a repo you did not write, the file at the repo root is **untrusted text injected into the system prompt** — a prompt-injection surface. Review `AGENTS.md` before running, or set `AGENT_INSTRUCTIONS_FILES=""` to disable loading on untrusted repos. See [Security](../../operations/security.md) and the full discussion in [Project Instructions](../../customization/project-instructions.md#security-agentsmd-is-untrusted-input).
:::

## Test it

### Behavior (BDD)

Verify this layer as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Scenario: AGENTS.md rule appears verbatim in the system prompt
  Given an AGENTS.md file exists at the repo root containing the rule
        "Never commit .env files or credentials"
  And the agent is initialized with load_project_instructions(cwd)
  When build_system_prompt is called with extra=load_project_instructions(cwd)
  Then the returned system prompt contains the string
       "Never commit .env files or credentials"
  And the model follows the rule when asked to handle an .env file
```

Run this as an integration scenario with the [BDD framework](../../guides/bdd-integration-testing.md).

The scenario fails before the change because `load_project_instructions` does not exist and the system prompt contains no project-specific text. After the change, the prompt includes the `## Project instructions (from AGENTS.md)` block verbatim.

### Existing tests

The Phase 12 test suite must still pass:

```bash
uv run pytest -q
```

No test should need to change — `build_system_prompt` signature is unchanged and `extra` defaults to `""`.

## Run it

```bash
# The repo already has AGENTS.md — the agent picks it up automatically
uv run main.py "what are the project's test conventions?"

# Disable loading for an untrusted repo
AGENT_INSTRUCTIONS_FILES="" uv run main.py "summarize this codebase"
```

On the first invocation, the model's first reply should reference `uv run pytest` (or whatever your `AGENTS.md` says) without being told — because the system prompt now carries those instructions.

## Recap

`src/project_instructions.py` discovers `AGENTS.md` and `CLAUDE.md` by walking from `cwd` to the git root, deduplicates symlinked files, and returns a formatted string. That string flows into the system prompt via `extra`. The agent now begins each session briefed on the repo's conventions without any per-session prompt engineering.

The next step adds per-session instruction injection and hook points that fire before and after each tool call.

→ [Layer 13.2 — Prompt Templates & Hooks](./2-prompt-templates-and-hooks.md)
