"""Tests for the planning eval: the valid_ordering grader and the suite.

valid_ordering is a pure answer-grader — it parses the ordered steps out of the
model's reply (after the last ``PLAN:`` marker, tolerating prose reasoning above
it) and checks the order against precedence constraints. Any valid topological
order passes; a violated dependency or a missing step fails.
"""

from __future__ import annotations

from evals.graders import valid_ordering
from evals.suites.planning import PLANNING_SUITE

REQUIRED = ["lint", "build", "test", "deploy"]
BEFORE = [("lint", "build"), ("build", "test"), ("test", "deploy")]


def test_valid_ordering_accepts_a_correct_topological_order():
    g = valid_ordering(REQUIRED, BEFORE)
    assert g("reasoning...\nPLAN: lint -> build -> test -> deploy").passed


def test_valid_ordering_ignores_reasoning_above_the_plan_marker():
    # The prose mentions steps out of order; only the PLAN: line is graded.
    answer = "First I should deploy, but wait — test comes first.\nPLAN: lint, build, test, deploy"
    assert valid_ordering(REQUIRED, BEFORE)(answer).passed


def test_valid_ordering_rejects_a_violated_constraint():
    g = valid_ordering(REQUIRED, BEFORE)
    res = g("PLAN: lint -> test -> build -> deploy")  # test before build
    assert res.passed is False
    assert "build" in res.detail and "test" in res.detail


def test_valid_ordering_rejects_a_missing_step():
    g = valid_ordering(REQUIRED, BEFORE)
    res = g("PLAN: lint -> build -> deploy")  # no test
    assert res.passed is False
    assert "test" in res.detail


def test_valid_ordering_uses_word_boundaries():
    # "retest" must not satisfy the "test" step.
    g = valid_ordering(["test", "deploy"], [("test", "deploy")])
    assert g("PLAN: retest -> deploy").passed is False


def test_valid_ordering_is_marked_as_answer_grader():
    assert getattr(valid_ordering(REQUIRED, BEFORE), "wants_answer", False) is True


# ── the planning suite ────────────────────────────────────────────────────────


def test_planning_suite_is_nonempty_and_answer_graded():
    assert len(PLANNING_SUITE) >= 5
    ids = [t.id for t in PLANNING_SUITE]
    assert len(ids) == len(set(ids))
    for t in PLANNING_SUITE:
        assert t.prompt.strip()
        assert getattr(t.grader, "wants_answer", False) is True
