"""Tests for the skill registry and skill-aware system prompt."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import prompts
import skills

TDD_MARKER = "Write a failing test before adding any new code"
EXPLAIN_MARKER = "Walk through code section by section"
SECURITY_MARKER = "Look for injection risks"


def test_active_skill_text_present():
    result = prompts.build_system_prompt(skills=["tdd"])
    assert TDD_MARKER in result


def test_deactivated_skill_text_absent():
    result = prompts.build_system_prompt(skills=["tdd"])
    assert EXPLAIN_MARKER not in result


def test_explain_skill_swaps_blocks():
    result = prompts.build_system_prompt(skills=["explain"])
    assert EXPLAIN_MARKER in result
    assert TDD_MARKER not in result


def test_empty_skills_list_yields_bare_prompt():
    result = prompts.build_system_prompt(skills=[])
    for marker in (TDD_MARKER, EXPLAIN_MARKER, SECURITY_MARKER):
        assert marker not in result


def test_unknown_skill_is_skipped():
    # Unknown names must not raise; known ones still apply.
    result = prompts.build_system_prompt(skills=["does-not-exist", "tdd"])
    assert TDD_MARKER in result


def test_none_skills_falls_back_to_active_default():
    # ACTIVE_SKILLS defaults to DEFAULT_SKILLS (tdd, git) when AGENT_SKILLS unset.
    result = prompts.build_system_prompt()
    expected = "\n".join(
        skills.SKILLS[s] for s in skills.ACTIVE_SKILLS if s in skills.SKILLS
    )
    if expected.strip():
        # At least the first active block should be present.
        assert skills.SKILLS[skills.ACTIVE_SKILLS[0]].strip().splitlines()[0] in result


def test_default_skills_are_tdd_and_git():
    assert skills.DEFAULT_SKILLS == ["tdd", "git"]


def test_registry_contains_expected_skills():
    for name in ("tdd", "git", "explain", "security"):
        assert name in skills.SKILLS


# --- CLI flag parsing (main._extract_skills) ---

sys.path.insert(0, str(Path(__file__).parent.parent))
import main  # noqa: E402


def test_extract_skills_absent_returns_none():
    task, active = main._extract_skills(["summarize", "this", "repo"])
    assert active is None
    assert task == ["summarize", "this", "repo"]


def test_extract_skills_single_name_then_multiword_task():
    task, active = main._extract_skills(["--skills", "explain", "walk me through the loop"])
    assert active == ["explain"]
    assert task == ["walk me through the loop"]


def test_extract_skills_multiple_space_separated_names():
    task, active = main._extract_skills(["--skills", "tdd", "git", "do the thing"])
    assert active == ["tdd", "git"]
    assert task == ["do the thing"]


def test_extract_skills_comma_separated_names():
    task, active = main._extract_skills(["--skills", "tdd,git", "do it"])
    assert active == ["tdd", "git"]
    assert task == ["do it"]


def test_extract_skills_empty_flag_is_bare_prompt():
    task, active = main._extract_skills(["--skills", "summarize this repo"])
    assert active == []
    assert task == ["summarize this repo"]


def test_extract_skills_preserves_sandbox_flag_before():
    task, active = main._extract_skills(["--sandbox", "--skills", "security", "audit it"])
    assert active == ["security"]
    assert task == ["--sandbox", "audit it"]
