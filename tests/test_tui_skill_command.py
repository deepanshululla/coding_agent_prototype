# tests/test_tui_skill_command.py

"""Test the /skill slash command."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tui.app import AgentApp


def test_skill_command_list_all_skills(tmp_path, monkeypatch):
    """Test /skill lists all available skills."""
    from tui.commands import dispatch

    # Create fake skills
    skills_dir = tmp_path / ".claude" / "skills"
    skills_dir.mkdir(parents=True)

    (skills_dir / "changelog").mkdir()
    (skills_dir / "changelog" / "SKILL.md").write_text(
        "---\nname: changelog\ndescription: Generate CHANGELOG\n---\n# Changelog\n"
    )

    (skills_dir / "test-skill").mkdir()
    (skills_dir / "test-skill" / "SKILL.md").write_text(
        "---\nname: test-skill\ndescription: Test skill\n---\n# Test\n"
    )

    # Change to tmp directory so skill discovery finds .claude/skills there
    monkeypatch.chdir(tmp_path)

    # Mock app (doesn't need to be fully functional for /skill)
    app: AgentApp = None  # ty: ignore[invalid-assignment]

    output = dispatch(app, "/skill")
    assert output is not None
    assert "Available skills:" in output
    assert "changelog" in output
    assert "test-skill" in output
    assert "Generate CHANGELOG" in output
    assert "Test skill" in output


def test_skill_command_load_specific_skill(tmp_path, monkeypatch):
    """Test /skill <name> loads a specific skill."""
    from tui.commands import dispatch

    # Create a skill
    skills_dir = tmp_path / ".claude" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "changelog").mkdir()
    (skills_dir / "changelog" / "SKILL.md").write_text(
        "---\nname: changelog\ndescription: Generate CHANGELOG\n---\n"
        "# Changelog\nRun git log and format it.\n"
    )

    monkeypatch.chdir(tmp_path)

    app: AgentApp = None  # ty: ignore[invalid-assignment]

    output = dispatch(app, "/skill changelog")
    assert output is not None
    assert "Loaded skill: changelog" in output
    assert "Run git log and format it" in output


def test_skill_command_unknown_skill(tmp_path, monkeypatch):
    """Test /skill <unknown> reports an error."""
    from tui.commands import dispatch

    monkeypatch.chdir(tmp_path)

    app: AgentApp = None  # ty: ignore[invalid-assignment]

    output = dispatch(app, "/skill nonexistent")
    assert output is not None
    assert "skill not found: nonexistent" in output.lower()


def test_skill_command_no_skills_directory(tmp_path, monkeypatch):
    """Test /skill when .claude/skills doesn't exist."""
    from tui.commands import dispatch

    monkeypatch.chdir(tmp_path)

    app: AgentApp = None  # ty: ignore[invalid-assignment]

    output = dispatch(app, "/skill")
    assert output is not None
    assert "no skills found" in output.lower() or "available skills:" in output.lower()
