"""Tests for the coding eval: suite shape and pytest-graded pass/fail.

No model needed — a fake runner stands in for the agent, writing a correct or
incorrect implementation into the workdir, and we assert the hidden tests grade
it accordingly. This proves the suite's stub+hidden-test wiring end to end.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import evals.harness as harness
from evals.harness import run_task
from evals.suites.coding import CODING_SUITE


def test_coding_suite_is_nonempty_and_well_formed():
    assert len(CODING_SUITE) >= 6
    ids = [t.id for t in CODING_SUITE]
    assert len(ids) == len(set(ids))
    for t in CODING_SUITE:
        assert t.prompt.strip()
        assert t.files  # ships a stub + hidden test
        assert callable(t.grader)


def _find(task_id):
    return next(t for t in CODING_SUITE if t.id == task_id)


def test_coding_task_passes_with_correct_impl(monkeypatch, tmp_path):
    task = _find("is-palindrome")

    async def fake(task, **kwargs):
        Path("solution.py").write_text(
            "def is_palindrome(s):\n"
            "    t = [c.lower() for c in s if c.isalnum()]\n"
            "    return t == t[::-1]\n"
        )
        return [{"type": "agent_end"}], []

    monkeypatch.setattr(harness, "run_agent_collecting", fake)
    result = asyncio.run(run_task(task))
    assert result.passed is True


def test_coding_task_fails_with_wrong_impl(monkeypatch, tmp_path):
    task = _find("is-palindrome")

    async def fake(task, **kwargs):
        Path("solution.py").write_text("def is_palindrome(s):\n    return False\n")
        return [{"type": "agent_end"}], []

    monkeypatch.setattr(harness, "run_agent_collecting", fake)
    result = asyncio.run(run_task(task))
    assert result.passed is False
