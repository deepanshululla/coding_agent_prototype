---
sidebar_position: 4
title: "Layer 13.4 — Agent Skills (Install & Read)"
description: Implement the open SKILL.md standard — discover installed skill folders, build a menu from their descriptions, and load full bodies on demand via a load_skill tool.
---

# Layer 13.4 — Agent Skills (Install & Read)

:::note Starting point
Layer 13.3 complete: `src/skills.py` holds a dict-based registry; `AGENT_SKILLS` controls which blocks are active; `build_system_prompt` accepts a `skills` parameter. The test suite passes.
:::

Dict-based skills live in Python source — to share them, you copy a string. The [Agent Skills standard](https://agentskills.io/specification) (an open format from Anthropic, adopted by Claude Code, Cursor, Gemini CLI, and others) solves this with a portable directory convention: a skill folder named after the skill, containing a `SKILL.md` with YAML frontmatter plus Markdown instructions. A skill written once works across every compliant client.

This layer adds:

1. A spec-compliant **loader** that discovers installed `SKILL.md` folders from `.claude/skills/`, `~/.claude/skills/`, and similar locations.
2. A **skills menu** — one line per discovered skill — inserted cheaply into the system prompt.
3. A **`load_skill` tool** the model calls to pull a skill's full body into context on demand (progressive disclosure).
4. Support for reading skills **already installed** by Claude Code or its plugins, controlled by `AGENT_CLAUDE_SKILLS=1`.

The install format is in [Installing Agent Skills](../../customization/installing-claude-skills.md). The multi-source discovery logic is in [Reading Installed Skills](../../customization/reading-installed-skills.md).

## What you'll learn

- The `SKILL.md` frontmatter spec: required `name` and `description`, optional `license`, `compatibility`, `metadata`, and `allowed-tools`.
- The three-stage progressive disclosure pattern: advertise all skills cheaply, load the body on demand, read bundled resources via existing tools.
- How `AGENT_CLAUDE_SKILLS=1` extends discovery to `~/.claude/skills` and enabled plugin skills.
- Why skills from disabled plugins are not surfaced.

## Build it

### Step 1 — Define the `Skill` dataclass and the spec-compliant loader

Add to `src/skills.py` (below the existing dict-based content):

```python
# src/skills.py (additions)
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


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
        print(f"  [skip skill] {skill_md}: description must be 1–1024 chars")
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
```

Non-compliant skills are skipped with a warning — the loader never silently trusts malformed frontmatter.

### Step 2 — Discover installed skills

```python
# src/skills.py (additions)
import json

SKILLS_DIR = os.environ.get("AGENT_SKILLS_DIR", "src/skills")


def _enabled_plugins() -> set[str]:
    """Return plugin names enabled in ~/.claude/settings.json."""
    settings = Path.home() / ".claude" / "settings.json"
    if not settings.exists():
        return set()
    data = json.loads(settings.read_text())
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
            # Only skills from enabled plugin marketplaces
            *[
                p for p in sorted((home / "plugins" / "marketplaces").glob("*"))
                if any(e.startswith(p.name) for e in enabled)
            ],
            Path(SKILLS_DIR),
        ]
    return [r for r in roots if r.exists()]


def discover_skills() -> dict[str, Skill]:
    """Return all valid installed skills. Later roots lose to earlier ones (project wins)."""
    skills: dict[str, Skill] = {}
    for root in installed_skill_roots():
        for skill_md in sorted(root.rglob("SKILL.md")):
            skill = _parse_skill(skill_md)
            if skill:
                skills.setdefault(skill.name, skill)  # first (highest-precedence) wins
    return skills


def skills_menu() -> str:
    """One line per discovered skill — cheap to keep in the system prompt."""
    discovered = discover_skills()
    if not discovered:
        return ""
    lines = ["## Available skills (call load_skill to activate)"]
    lines += [f"- {name}: {s.description}" for name, s in discovered.items()]
    return "\n".join(lines)
```

:::note skills_menu cost
Each line is roughly 20–50 tokens. Even with 30 installed skills the menu costs under 1 500 tokens — far less than loading every body. The menu stays in the system prompt permanently; skill bodies load only when called.
:::

### Step 3 — Add the `load_skill` tool

Register a `load_skill` tool so the model can pull a skill body into context when it decides the skill applies:

```python
# src/tools.py (additions)
from skills import discover_skills

async def load_skill(name: str) -> str:
    """Return the full instruction body of an installed skill by name."""
    skill = discover_skills().get(name)
    if skill is None:
        return f"Error: no installed skill named {name!r}"
    return skill.body
```

Add the schema entry to `TOOLS_SCHEMA`:

```python
{
    "type": "function",
    "function": {
        "name": "load_skill",
        "description": (
            "Load the full instruction body of an installed skill. "
            "Call this when you recognize a skill in the skills menu applies to the current task."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill name as listed in the skills menu"},
            },
            "required": ["name"],
        },
    },
},
```

Add to `TOOL_REGISTRY`:

```python
TOOL_REGISTRY["load_skill"] = load_skill
```

### Step 4 — Inject the menu into the prompt

In `build_system_prompt`, add the skills menu between the tool list and the guidelines:

```python
# src/prompts.py (updated)
from skills import skills_menu

def build_system_prompt(cwd=None, extra="", skills=None) -> str:
    ...
    menu = skills_menu()
    ...
    return f"""...

{menu}

## Guidelines
...
"""
```

### Step 5 — Install a SKILL.md (example)

Create a test skill to verify the pipeline end-to-end:

```bash
mkdir -p .claude/skills/changelog
```

```markdown
<!-- .claude/skills/changelog/SKILL.md -->
---
name: changelog
description: Generate a CHANGELOG entry in Keep-a-Changelog format. Use when the
  user asks for a changelog, release notes, or a summary of recent changes.
license: MIT
metadata:
  author: you
  version: "1.0"
---

# Changelog entry

1. Run `git log --oneline <from>..<to>` to list commits in the range.
2. Group by type: Added, Changed, Deprecated, Removed, Fixed, Security.
3. Write each entry as "- <imperative summary> ([#PR](url))".
4. Output the block under the version heading: `## [Unreleased] - YYYY-MM-DD`.
```

## Test it

### Behavior (BDD)

Verify this layer as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Scenario: Installed SKILL.md is discovered, advertised, and loaded on demand
  Given a valid SKILL.md exists at .claude/skills/changelog/SKILL.md
  And the agent is initialized with skills_menu() in the system prompt
  When the system prompt is inspected
  Then it contains "changelog: Generate a CHANGELOG entry in Keep-a-Changelog format"
  When the model calls load_skill with name="changelog"
  Then the tool returns the skill body containing "git log --oneline"
  And the model subsequently follows the changelog generation instructions
```

Run this as an integration scenario with the [BDD framework](../../guides/bdd-integration-testing.md).

The scenario fails before the change because `discover_skills()` does not exist, the menu is absent from the prompt, and `load_skill` is not in `TOOL_REGISTRY`. After the change, all three steps pass.

### Existing tests

```bash
uv run pytest -q
```

The `load_skill` tool follows the same "never raise, return error string" contract as all other tools, so existing tool-dispatch tests are unaffected.

## Run it

```bash
# The menu now appears in the system prompt automatically
uv run main.py "generate a changelog entry for this week's commits"
# → model sees "changelog: Generate a CHANGELOG entry..." in the menu,
#   calls load_skill("changelog"), then follows the instructions.

# Enable personal ~/.claude/skills and enabled plugin skills
AGENT_CLAUDE_SKILLS=1 uv run main.py "make a mermaid diagram of the agent loop"
```

## Recap

The spec-compliant loader discovers `SKILL.md` folders from `.claude/skills/`, optionally `~/.claude/skills/` and enabled plugin skill directories. The skills menu (one line per skill) lives permanently in the system prompt for ~1 500 tokens. When the model sees a matching task, it calls `load_skill` to pull the full body — stage 2 of progressive disclosure. Bundled `references/` files load via `read_file` as needed (stage 3). Skills from disabled plugins are excluded.

The next layer takes this further: connecting MCP servers and merging their tools into the same registry so they're callable exactly like the 7 built-ins.

→ [Layer 13.5 — MCP Integration](./5-mcp-integration.md)
