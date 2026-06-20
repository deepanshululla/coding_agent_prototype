"""Tests for project instruction discovery (AGENTS.md / CLAUDE.md)."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import project_instructions


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def test_loads_agents_md_from_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_INSTRUCTIONS_FILES", raising=False)
    _git_init(tmp_path)
    (tmp_path / "AGENTS.md").write_text("Never commit .env files or credentials", encoding="utf-8")
    result = project_instructions.load_project_instructions(str(tmp_path))
    assert "Never commit .env files or credentials" in result
    assert "## Project instructions (from AGENTS.md)" in result


def test_returns_empty_when_no_file(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_INSTRUCTIONS_FILES", raising=False)
    _git_init(tmp_path)
    result = project_instructions.load_project_instructions(str(tmp_path))
    assert result == ""


def test_discovers_file_in_parent_up_to_git_root(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_INSTRUCTIONS_FILES", raising=False)
    _git_init(tmp_path)
    (tmp_path / "AGENTS.md").write_text("ROOT RULE", encoding="utf-8")
    sub = tmp_path / "pkg" / "module"
    sub.mkdir(parents=True)
    result = project_instructions.load_project_instructions(str(sub))
    assert "ROOT RULE" in result


def test_symlinked_file_deduplicated(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_INSTRUCTIONS_FILES", raising=False)
    _git_init(tmp_path)
    agents = tmp_path / "AGENTS.md"
    agents.write_text("ONLY ONCE", encoding="utf-8")
    claude = tmp_path / "CLAUDE.md"
    claude.symlink_to(agents)
    result = project_instructions.load_project_instructions(str(tmp_path))
    assert result.count("ONLY ONCE") == 1


def test_both_files_included_with_distinct_headers(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_INSTRUCTIONS_FILES", raising=False)
    _git_init(tmp_path)
    (tmp_path / "AGENTS.md").write_text("AGENTS BODY", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("CLAUDE BODY", encoding="utf-8")
    result = project_instructions.load_project_instructions(str(tmp_path))
    assert "## Project instructions (from AGENTS.md)" in result
    assert "## Project instructions (from CLAUDE.md)" in result
    assert "AGENTS BODY" in result
    assert "CLAUDE BODY" in result


def test_env_var_empty_disables_loading(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_INSTRUCTIONS_FILES", "")
    _git_init(tmp_path)
    (tmp_path / "AGENTS.md").write_text("SHOULD NOT APPEAR", encoding="utf-8")
    result = project_instructions.load_project_instructions(str(tmp_path))
    assert result == ""


def test_env_var_custom_filename(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_INSTRUCTIONS_FILES", ".cursorrules")
    _git_init(tmp_path)
    (tmp_path / ".cursorrules").write_text("CURSOR RULE", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("AGENTS RULE", encoding="utf-8")
    result = project_instructions.load_project_instructions(str(tmp_path))
    assert "CURSOR RULE" in result
    assert "AGENTS RULE" not in result
