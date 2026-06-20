---
sidebar_position: 3.5
title: Installing Agent Skills
description: Load and install Agent Skills (the open SKILL.md standard from agentskills.io) into the agent — the compliant frontmatter, directory layout, loader, progressive disclosure, and validation.
---

# Installing Agent Skills

The [Skills](./skills.md) page covers skills defined inline as a Python dict. This page covers
loading **[Agent Skills](https://agentskills.io)** — the portable, open `SKILL.md` folder
standard (originally from Anthropic, now adopted by Claude Code, Cursor, Gemini CLI, OpenCode,
Goose, and many others). A skill written once works across every compliant client, including
this agent.

:::note Status & compliance
A supported design that extends the [Skills](./skills.md) system. v1 ships neither loader; both
are documented designs. The format below follows the
[Agent Skills specification](https://agentskills.io/specification) exactly, so skills you load
here are portable to any other compliant client (and vice versa).
:::

## Skill directory layout

A skill is a **directory** whose name matches the skill's `name`, containing a required
`SKILL.md` plus optional bundled resources:

```
pdf-processing/
├── SKILL.md          # Required: YAML frontmatter + Markdown instructions
├── scripts/          # Optional: executable code the agent may run
├── references/       # Optional: docs loaded on demand
└── assets/           # Optional: templates, schemas, data files
```

## `SKILL.md` frontmatter

The file is YAML frontmatter followed by a Markdown body. The spec defines these fields:

| Field | Required | Constraint |
|---|---|---|
| `name` | **Yes** | ≤64 chars; lowercase `a-z`, `0-9`, `-`; no leading/trailing/consecutive hyphens; **must match the directory name** |
| `description` | **Yes** | 1–1024 chars, non-empty; says *what* it does and *when* to use it |
| `license` | No | License name or reference to a bundled license file |
| `compatibility` | No | ≤500 chars; environment needs (intended product, packages, network) |
| `metadata` | No | Arbitrary string→string map (e.g. `author`, `version`) |
| `allowed-tools` | No | Space-separated pre-approved tools (experimental) |

```markdown
---
name: pdf-processing
description: Extract text and tables from PDFs, fill forms, and merge files. Use
  when the user provides a PDF or mentions PDFs, forms, or document extraction.
license: Apache-2.0
metadata:
  author: example-org
  version: "1.0"
allowed-tools: Bash(python:*) Read
---

# PDF processing

1. Run `python scripts/extract_text.py <path>` to get the raw text.
2. See [the reference guide](references/REFERENCE.md) for table handling.
```

The `description` is the most important field — it's all the agent sees at discovery time, so it
must carry the keywords that tell the model *when* to reach for the skill.

## Where skills install from

"Installing" a skill is placing its folder in a directory the loader scans:

| Location | Scope | Env var |
|---|---|---|
| `./.claude/skills/<name>/` | Project-local | — |
| `~/.claude/skills/<name>/` | Personal (all projects) | — |
| `src/skills/<name>/` | Bundled with the agent | `AGENT_SKILLS_DIR` |

```bash
# Copy a skill folder, or clone a repo of skills:
cp -r ./pdf-processing ~/.claude/skills/
git clone https://github.com/some/skills-repo .claude/skills/skills-repo
```

To pick up skills **already installed** by Claude Code or its plugins (and respect which are
enabled), see [Reading Installed Skills](./reading-installed-skills.md).

## The loader (spec-compliant)

Parse each `SKILL.md` into a record, **validating** against the spec — invalid skills are
skipped with a warning rather than silently trusted. Frontmatter parsing needs a YAML reader
(`pyyaml`).

```python
# src/skills.py
import re
from dataclasses import dataclass, field
from pathlib import Path
import yaml

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")  # no leading/trailing/consecutive hyphens


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
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    _, frontmatter, body = text.split("---", 2)
    meta = yaml.safe_load(frontmatter) or {}

    name = str(meta.get("name", "")).strip()
    description = str(meta.get("description", "")).strip()

    # Spec validation — skip non-compliant skills.
    if not (1 <= len(name) <= 64 and NAME_RE.match(name)):
        print(f"  [skip] {skill_md}: invalid name {name!r}")
        return None
    if name != skill_md.parent.name:
        print(f"  [skip] {skill_md}: name {name!r} != dir {skill_md.parent.name!r}")
        return None
    if not (1 <= len(description) <= 1024):
        print(f"  [skip] {skill_md}: description must be 1–1024 chars")
        return None
    compatibility = str(meta.get("compatibility", "")).strip()
    if len(compatibility) > 500:
        print(f"  [skip] {skill_md}: compatibility exceeds 500 chars")
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


def discover_skills() -> dict[str, Skill]:
    roots = [Path(".claude/skills"), Path.home() / ".claude" / "skills", Path("src/skills")]
    skills: dict[str, Skill] = {}
    for root in roots:
        for skill_md in sorted(root.glob("*/SKILL.md")) if root.exists() else []:
            skill = _parse_skill(skill_md)
            if skill:
                skills[skill.name] = skill  # later roots override earlier names
    return skills
```

## Progressive disclosure (the three stages)

The spec is explicit about loading skills in stages so many can be on hand cheaply. Mirror it:

| Stage | What loads | ~Cost | Here |
|---|---|---|---|
| **1. Metadata** | `name` + `description` of every skill | ~100 tokens each | A menu line per skill, kept in the system prompt |
| **2. Instructions** | the full `SKILL.md` body | `<5000` tokens | Loaded when the skill activates (via `load_skill`) |
| **3. Resources** | files in `scripts/`/`references/`/`assets/` | as needed | Read on demand with the `read_file` tool / run via `bash` |

```python
# src/tools.py — stage 2: pull a skill's instructions on demand
async def load_skill(name: str) -> str:
    skill = discover_skills().get(name)
    if skill is None:
        return f"Error: no installed skill named {name!r}"
    return skill.body
```

Register `load_skill` in `TOOLS_SCHEMA`/`TOOL_REGISTRY` (see [Adding a Tool](../tools/adding-a-tool.md)),
and put each skill's `name: description` in the prompt. Stage 3 needs no special machinery — a
skill body says `references/REFERENCE.md` and the model reads it with the existing
[`read_file`](../tools/built-in-tools.md) tool; relative paths resolve from the skill folder
(`skill.path`). Keep `SKILL.md` under ~500 lines and push detail into `references/`.

## `allowed-tools` and the command allowlist

The optional `allowed-tools` field lists tools a skill is pre-approved to use, e.g.
`Bash(python:*) Read`. It maps directly onto this project's
[Command Allowlist](../operations/command-allowlist.md): treat a skill's `allowed-tools` as a
*request*, not a grant. The skill can only run what your allowlist already permits — a skill
declaring `Bash(rm:*)` still can't run `rm` unless you allowed it. Honor `allowed-tools` as an
**intersection** with your policy, never a widening of it.

## Validating skills

The spec ships a reference validator. Use it in CI or before installing a third-party skill:

```bash
skills-ref validate ./pdf-processing
```

It checks the frontmatter and naming rules the loader above enforces at runtime.

## Bundled scripts and the security boundary

Skills often ship scripts the model is told to run (`python scripts/extract_text.py …`).
Installing a skill can therefore introduce code the agent will execute via `bash`:

- Read `SKILL.md` and its bundled files before installing a skill from an untrusted source.
- Scripts run through `bash`, so they're subject to your
  [Command Allowlist](../operations/command-allowlist.md) — a skill needing `python` only works
  if `python` is allowed. Cross-check the skill's `allowed-tools` against your policy.
- Run untrusted skills in a [container](../operations/containerization.md).

:::warning
A skill's `description` enters the prompt and its body loads into context — both are a
prompt-injection surface. Vet skills like any code you install. See
[Security Model](../operations/security.md).
:::

## Related pages

- [Reading Installed Skills](./reading-installed-skills.md) — discover skills already on the machine
- [Skills](./skills.md) — the underlying skills system and dict-based definitions
- [Adding a Tool](../tools/adding-a-tool.md) — for the `load_skill` tool
- [Agent Skills specification](https://agentskills.io/specification) — the authoritative format spec
- [Settings Reference](../operations/settings.md) — `AGENT_SKILLS`, `AGENT_SKILLS_DIR`
