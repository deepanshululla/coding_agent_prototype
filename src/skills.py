"""Named instruction blocks composed into the system prompt.

A *skill* is a named block of Markdown instructions injected into the system
prompt by name. The active set is read from the ``AGENT_SKILLS`` environment
variable (comma-separated) and falls back to ``DEFAULT_SKILLS`` when unset.
``build_system_prompt`` accepts an explicit ``skills`` list that overrides this
default per call (the CLI ``--skills`` flag wires through to it).
"""

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


def _resolve_active_skills() -> list[str]:
    env = os.environ.get("AGENT_SKILLS", "")
    if env:
        return [s.strip() for s in env.split(",") if s.strip()]
    return list(DEFAULT_SKILLS)


ACTIVE_SKILLS: list[str] = _resolve_active_skills()
