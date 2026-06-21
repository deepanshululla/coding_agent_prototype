"""Tests for the reasoning eval: answer-graders and the reasoning suite.

The graders are pure functions of the model's final answer string, so they need
no model. The suite is checked for shape and that every task is an answer-graded
task (graded on what the model said, not the workdir).
"""

from __future__ import annotations

from evals.graders import answer_contains, exact_answer
from evals.suites.reasoning import REASONING_SUITE

# ── exact_answer ──────────────────────────────────────────────────────────────


def test_exact_answer_matches_bare_last_line():
    g = exact_answer("42")
    assert g("reasoning here\n42").passed


def test_exact_answer_matches_framed_answer():
    g = exact_answer("42")
    assert g("step 1...\nThe answer is 42.").passed  # last token + trailing punct


def test_exact_answer_normalizes_case_and_thousands_commas():
    assert exact_answer("Tuesday")("so it is tuesday").passed
    assert exact_answer("1000")("the total is 1,000").passed


def test_exact_answer_rejects_wrong_answer():
    g = exact_answer("42")
    res = g("the answer is 41")
    assert res.passed is False
    assert "41" in res.detail


def test_exact_answer_rejects_empty():
    assert exact_answer("42")("").passed is False


def test_exact_answer_is_marked_as_answer_grader():
    assert getattr(exact_answer("x"), "wants_answer", False) is True


def test_answer_contains_is_case_insensitive_and_marked():
    g = answer_contains("NEEDLE")
    assert g("there is a needle in here").passed
    assert g("nothing").passed is False
    assert getattr(g, "wants_answer", False) is True


# ── the reasoning suite ───────────────────────────────────────────────────────


def test_reasoning_suite_is_nonempty_and_answer_graded():
    assert len(REASONING_SUITE) >= 6
    ids = [t.id for t in REASONING_SUITE]
    assert len(ids) == len(set(ids))  # unique ids
    for t in REASONING_SUITE:
        assert t.prompt.strip()
        # Every reasoning task is graded on the spoken answer, not the workdir.
        assert getattr(t.grader, "wants_answer", False) is True
