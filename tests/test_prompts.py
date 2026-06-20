"""Tests for the system prompt builder."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import prompts


def test_prompt_contains_cwd(tmp_path):
    result = prompts.build_system_prompt(cwd=str(tmp_path))
    assert str(tmp_path) in result


def test_prompt_contains_today():
    result = prompts.build_system_prompt()
    today = date.today().isoformat()
    assert today in result


def test_prompt_contains_all_tool_names():
    result = prompts.build_system_prompt()
    for name in ("read_file", "write_file", "edit_file", "bash", "grep", "find_files", "list_dir"):
        assert name in result, f"Tool {name!r} missing from system prompt"


def test_prompt_extra_is_appended():
    result = prompts.build_system_prompt(extra="CUSTOM MARKER")
    assert "CUSTOM MARKER" in result
