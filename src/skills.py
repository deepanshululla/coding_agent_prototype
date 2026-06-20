"""Named instruction blocks composed into the system prompt.

A *skill* is a named block of Markdown instructions injected into the system
prompt by name. The active set is read from the ``AGENT_SKILLS`` environment
variable (comma-separated) and falls back to ``DEFAULT_SKILLS`` when unset.
``build_system_prompt`` accepts an explicit ``skills`` list that overrides this
default per call (the CLI ``--skills`` flag wires through to it).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

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


# ── Spec-compliant Agent Skills (SKILL.md folders) ───────────────────────────
#
# The open Agent Skills standard packages a skill as a directory named after the
# skill, containing a ``SKILL.md`` with YAML frontmatter (required ``name`` and
# ``description``) plus a Markdown body. Discovery is cheap (one menu line per
# skill in the system prompt); the full body loads on demand via ``load_skill``.

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

SKILLS_DIR = os.environ.get("AGENT_SKILLS_DIR", "src/skills")


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path
    license: str = ""
    compatibility: str = ""
    metadata: dict = field(default_factory=dict)
    allowed_tools: str = ""


def _parse_skill(skill_md: Path) -> Skill | None:
    """Parse and validate one SKILL.md; return None if it fails spec validation."""
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    _, frontmatter, body = text.split("---", 2)
    meta = yaml.safe_load(frontmatter) or {}

    name = str(meta.get("name", "")).strip()
    description = str(meta.get("description", "")).strip()

    if not (1 <= len(name) <= 64 and NAME_RE.match(name)):
        print(f"  [skip skill] {skill_md}: invalid name {name!r}")
        return None
    if name != skill_md.parent.name:
        print(f"  [skip skill] {skill_md}: name {name!r} != dir {skill_md.parent.name!r}")
        return None
    if not (1 <= len(description) <= 1024):
        print(f"  [skip skill] {skill_md}: description must be 1-1024 chars")
        return None
    compatibility = str(meta.get("compatibility", "")).strip()
    if len(compatibility) > 500:
        print(f"  [skip skill] {skill_md}: compatibility exceeds 500 chars")
        return None

    return Skill(
        name=name,
        description=description,
        body=body.strip(),
        path=skill_md.parent,
        license=str(meta.get("license", "")).strip(),
        compatibility=compatibility,
        metadata=meta.get("metadata") or {},
        allowed_tools=str(meta.get("allowed-tools", "")).strip(),
    )


def _enabled_plugins() -> set[str]:
    """Return plugin names enabled in ~/.claude/settings.json (empty if absent)."""
    settings = Path.home() / ".claude" / "settings.json"
    if not settings.exists():
        return set()
    try:
        data = json.loads(settings.read_text())
    except (json.JSONDecodeError, OSError):
        return set()
    return {name for name, on in data.get("enabledPlugins", {}).items() if on}


def installed_skill_roots() -> list[Path]:
    """Return directories to scan for SKILL.md folders, in precedence order."""
    roots: list[Path] = [Path(".claude/skills"), Path(SKILLS_DIR)]
    if os.environ.get("AGENT_CLAUDE_SKILLS") == "1":
        home = Path.home() / ".claude"
        enabled = _enabled_plugins()
        roots = [
            Path(".claude/skills"),
            home / "skills",
            # Only skills from enabled plugin marketplaces.
            *[
                p
                for p in sorted((home / "plugins" / "marketplaces").glob("*"))
                if any(e.startswith(p.name) for e in enabled)
            ],
            Path(SKILLS_DIR),
        ]
    return [r for r in roots if r.exists()]


def discover_skills() -> dict[str, Skill]:
    """Return all valid installed skills. Earlier roots win on name collision."""
    discovered: dict[str, Skill] = {}
    for root in installed_skill_roots():
        for skill_md in sorted(root.rglob("SKILL.md")):
            skill = _parse_skill(skill_md)
            if skill:
                discovered.setdefault(skill.name, skill)  # highest-precedence wins
    return discovered


def skills_menu() -> str:
    """One line per discovered skill — cheap to keep in the system prompt."""
    discovered = discover_skills()
    if not discovered:
        return ""
    lines = ["## Available skills (call load_skill to activate)"]
    lines += [f"- {name}: {s.description}" for name, s in discovered.items()]
    return "\n".join(lines)
