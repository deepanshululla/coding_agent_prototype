---
sidebar_position: 3.6
title: Reading Installed Skills
description: Discover and read Agent Skills already installed on the machine — personal ~/.claude/skills, project .claude/skills, and enabled plugin/marketplace skills — respecting which plugins are enabled.
---

# Reading Installed Skills

[Installing Agent Skills](./installing-claude-skills.md) covers *adding* a skill folder. This
page covers the other direction: **discovering and reading the skills already installed** on
the machine — the ones Claude Code (or you) have set up — so the agent can use them without
copying anything into the project. All of them follow the same
[Agent Skills standard](https://agentskills.io/specification), so one compliant loader reads
every source.

:::note Status
A supported design extending the [skills loader](./installing-claude-skills.md). Reading the
shared `~/.claude` locations is **opt-in** via `AGENT_CLAUDE_SKILLS=1`, so the agent never
slurps your global skills unless you ask it to.
:::

## Where skills are already installed

On a machine with Claude Code, skills live in several places. The agent can read all of them:

| Location | Scope | Notes |
|---|---|---|
| `./.claude/skills/<name>/SKILL.md` | Project | Checked into the repo; highest precedence |
| `~/.claude/skills/<name>/SKILL.md` | Personal | Your global skills, all projects |
| `~/.claude/plugins/marketplaces/<market>/<name>/SKILL.md` | Marketplace | Skills from installed marketplaces |
| `~/.claude/plugins/cache/<plugin>/…/SKILL.md` | Plugin | Skills bundled inside installed plugins |
| `src/skills/<name>/SKILL.md` | Bundled | Ships with this agent (`AGENT_SKILLS_DIR`) |

The `SKILL.md` format is identical everywhere — the
[Agent Skills frontmatter](./installing-claude-skills.md#skillmd-frontmatter) (`name` +
`description`, plus optional fields). So the one
[spec-compliant loader](./installing-claude-skills.md#the-loader-spec-compliant) reads them all.

## Respect what's enabled

Not every installed plugin is active. Claude Code records enabled plugins in
`~/.claude/settings.json`:

```json
{
  "enabledPlugins": {
    "frontend-design@claude-plugins-official": true,
    "huggingface-skills@claude-plugins-official": true,
    "feature-dev@claude-plugins-official": false
  }
}
```

A faithful reader **honors that flag** — surfacing a skill from a plugin the user disabled
would be wrong. Personal (`~/.claude/skills`) and project (`.claude/skills`) skills have no
enable flag; they're always available.

```python
# src/skills.py
import json
from pathlib import Path

def _enabled_plugins() -> set[str]:
    settings = Path.home() / ".claude" / "settings.json"
    if not settings.exists():
        return set()
    data = json.loads(settings.read_text())
    return {name for name, on in data.get("enabledPlugins", {}).items() if on}
```

## Discovering everything

Reuse the validating [`_parse_skill`](./installing-claude-skills.md#the-loader-spec-compliant)
loader. Scan each root, parse every `SKILL.md` (the loader already enforces the spec's naming
and length rules, so malformed skills are skipped), and merge with precedence — later roots
lose to earlier ones, so project skills win over personal, which win over plugin defaults.

```python
# src/skills.py
import os
from pathlib import Path

def installed_skill_roots() -> list[Path]:
    roots = [Path(".claude/skills"), Path(os.environ.get("AGENT_SKILLS_DIR", "src/skills"))]
    # Reading the shared ~/.claude locations is opt-in.
    if os.environ.get("AGENT_CLAUDE_SKILLS") == "1":
        home = Path.home() / ".claude"
        roots = [
            Path(".claude/skills"),
            home / "skills",
            *sorted((home / "plugins" / "marketplaces").glob("*")),
            Path(os.environ.get("AGENT_SKILLS_DIR", "src/skills")),
        ]
    return [r for r in roots if r.exists()]


def discover_installed_skills() -> dict[str, "Skill"]:
    skills: dict[str, Skill] = {}
    for root in installed_skill_roots():
        for skill_md in sorted(root.rglob("SKILL.md")):
            skill = _parse_skill(skill_md)
            if skill:
                skills[skill.name] = skill
    return skills
```

:::tip Namespacing collisions
Personal and project skills are addressed by their bare `name`. For plugin/marketplace skills,
prefix with the plugin to avoid clashes — `plugin:skill` (e.g. `huggingface-skills:hf-cli`) —
exactly how Claude Code disambiguates them. Store the prefixed name as the registry key so two
skills called `review` from different plugins coexist. (The bare `name` still has to satisfy the
spec's [naming rules](./installing-claude-skills.md#skillmd-frontmatter); the prefix is the
agent's own addressing, not part of the skill's `name`.)
:::

## Don't load forty skill bodies into the prompt

A real machine can have **dozens** of installed skills. Injecting every body into the system
prompt would blow the context window immediately — which is exactly what the spec's
[progressive disclosure](./installing-claude-skills.md#progressive-disclosure-the-three-stages)
prevents:

- **Advertise** every discovered skill as one line — `name: description` (stage 1, ~100 tokens
  each) — so the model knows what exists and *when* each applies.
- **Load** a skill's full body only when the model asks, via the `load_skill` tool (stage 2).
  Bundled `references/` files load later still (stage 3), via `read_file`.

```python
def skills_menu() -> str:
    """One line per installed skill — cheap to keep in the system prompt."""
    return "\n".join(
        f"- {name}: {s.description}" for name, s in discover_installed_skills().items()
    )
```

With the menu in the prompt and `load_skill` registered as a tool, the agent can reach any
installed skill without any of them costing more than a line of context until it's used.

## Enabling it

```bash
# .env
AGENT_CLAUDE_SKILLS=1          # read ~/.claude/skills and enabled plugin skills
AGENT_SKILLS_DIR=src/skills    # the agent's own bundled skills (default)
```

```bash
uv run main.py "make a mermaid sequence diagram of the agent loop"
# → the model sees the installed `mermaid` skill in the menu, calls load_skill("mermaid"),
#   and follows its instructions.
```

## Security

Reading installed skills means **their text enters your prompt and their bundled scripts may
run via `bash`**. Two guards:

- The agent only reads skills from plugins the user has **enabled** in `settings.json` — it
  won't surface skills from disabled or untrusted plugins.
- A skill body is still untrusted text from whoever wrote it. The same vetting,
  [allowlist](../operations/command-allowlist.md), and [container](../operations/containerization.md)
  advice from
  [Installing Agent Skills](./installing-claude-skills.md#bundled-scripts-and-the-security-boundary)
  applies. See [Security Model](../operations/security.md).

## Related pages

- [Installing Agent Skills](./installing-claude-skills.md) — the `SKILL.md` format and the loader this builds on
- [Skills](./skills.md) — the underlying skills system
- [Agent Skills specification](https://agentskills.io/specification) — the authoritative format spec
- [Settings Reference](../operations/settings.md) — `AGENT_CLAUDE_SKILLS`, `AGENT_SKILLS`, `AGENT_SKILLS_DIR`
