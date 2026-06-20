"""Tests for spec-compliant Agent Skills (SKILL.md folders).

Covers parsing/validation of SKILL.md frontmatter, discovery from
``.claude/skills/``, the system-prompt menu, and the ``load_skill`` tool.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import prompts
import skills
import tools


# ── fixtures ─────────────────────────────────────────────────────────────────


def _write_skill(root: Path, name: str, frontmatter: str, body: str = "body") -> Path:
    """Write a SKILL.md under ``root/<name>/`` and return its path."""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    md = d / "SKILL.md"
    md.write_text(f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")
    return md


# ── _parse_skill: valid ──────────────────────────────────────────────────────


def test_parse_valid_skill(tmp_path):
    md = _write_skill(
        tmp_path,
        "demo",
        "name: demo\ndescription: A demo skill that does demo things.",
        body="# Demo\n\nDo the thing.",
    )
    skill = skills._parse_skill(md)
    assert skill is not None
    assert skill.name == "demo"
    assert skill.description == "A demo skill that does demo things."
    assert "Do the thing." in skill.body
    assert skill.path == md.parent


def test_parse_skill_optional_fields(tmp_path):
    md = _write_skill(
        tmp_path,
        "demo",
        "name: demo\ndescription: d\nlicense: MIT\n"
        'metadata:\n  author: you\nallowed-tools: read_file',
    )
    skill = skills._parse_skill(md)
    assert skill is not None
    assert skill.license == "MIT"
    assert skill.metadata == {"author": "you"}
    assert skill.allowed_tools == "read_file"


# ── _parse_skill: rejection cases ────────────────────────────────────────────


def test_parse_rejects_missing_frontmatter(tmp_path):
    d = tmp_path / "demo"
    d.mkdir()
    md = d / "SKILL.md"
    md.write_text("no frontmatter here\n", encoding="utf-8")
    assert skills._parse_skill(md) is None


def test_parse_rejects_name_dir_mismatch(tmp_path):
    md = _write_skill(tmp_path, "demo", "name: other\ndescription: d")
    assert skills._parse_skill(md) is None


def test_parse_rejects_invalid_name_chars(tmp_path):
    md = _write_skill(tmp_path, "Demo_Skill", "name: Demo_Skill\ndescription: d")
    assert skills._parse_skill(md) is None


def test_parse_rejects_name_too_long(tmp_path):
    long_name = "a" * 65
    md = _write_skill(tmp_path, long_name, f"name: {long_name}\ndescription: d")
    assert skills._parse_skill(md) is None


def test_parse_rejects_empty_description(tmp_path):
    md = _write_skill(tmp_path, "demo", "name: demo\ndescription: ''")
    assert skills._parse_skill(md) is None


def test_parse_rejects_description_too_long(tmp_path):
    long_desc = "x" * 1025
    md = _write_skill(tmp_path, "demo", f"name: demo\ndescription: {long_desc}")
    assert skills._parse_skill(md) is None


# ── discovery + menu ─────────────────────────────────────────────────────────


def test_discover_finds_project_claude_skills():
    discovered = skills.discover_skills()
    assert "changelog" in discovered
    assert discovered["changelog"].path.name == "changelog"


def test_skills_menu_lists_changelog():
    menu = skills.skills_menu()
    assert "changelog: Generate a CHANGELOG entry" in menu


def test_discover_precedence_first_root_wins(tmp_path, monkeypatch):
    # Two roots, same skill name; the earlier root must win.
    a = tmp_path / "a"
    b = tmp_path / "b"
    _write_skill(a, "dup", "name: dup\ndescription: from-a")
    _write_skill(b, "dup", "name: dup\ndescription: from-b")
    monkeypatch.setattr(skills, "installed_skill_roots", lambda: [a, b])
    discovered = skills.discover_skills()
    assert discovered["dup"].description == "from-a"


def test_installed_roots_excludes_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_CLAUDE_SKILLS", raising=False)
    monkeypatch.setattr(skills, "SKILLS_DIR", str(tmp_path / "does-not-exist"))
    roots = skills.installed_skill_roots()
    # Only existing roots returned; .claude/skills exists at repo root.
    assert all(r.exists() for r in roots)


def test_enabled_plugins_empty_when_no_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(skills.Path, "home", classmethod(lambda cls: tmp_path))
    assert skills._enabled_plugins() == set()


# ── prompt injection ─────────────────────────────────────────────────────────


def test_prompt_contains_skills_menu():
    result = prompts.build_system_prompt()
    assert "changelog: Generate a CHANGELOG entry" in result
    assert "load_skill" in result


# ── load_skill tool ──────────────────────────────────────────────────────────


async def test_load_skill_returns_body():
    body = await tools.load_skill("changelog")
    assert "git log --oneline" in body


async def test_load_skill_unknown_returns_error():
    result = await tools.load_skill("nonexistent")
    assert result.startswith("Error:")
    assert "nonexistent" in result


def test_load_skill_registered():
    assert "load_skill" in tools.TOOL_REGISTRY
    names = [s["function"]["name"] for s in tools.TOOLS_SCHEMA]
    assert "load_skill" in names
