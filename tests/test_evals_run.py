"""Tests for the eval runner's pure pieces: suite lookup and reporting.

The runner's I/O (argument parsing, driving real agent runs) is a thin shell;
the parts worth testing are the suite registry and the report formatting, both
of which are pure and deterministic.
"""

import pytest

from evals.harness import EvalResult
from evals.run import format_report, get_suite


def test_get_suite_returns_known_suite():
    tasks = get_suite("smoke")
    assert len(tasks) >= 1
    assert all(t.id for t in tasks)


def test_get_suite_unknown_raises_with_helpful_message():
    with pytest.raises(KeyError) as exc:
        get_suite("does-not-exist")
    assert "smoke" in str(exc.value)  # lists what *is* available


def _result(task_id, passed, tokens=100):
    return EvalResult(
        task_id=task_id, passed=passed, detail="", total_tokens=tokens, duration_s=0.5
    )


def test_format_report_shows_pass_and_fail_and_totals():
    results = [_result("a", True, 100), _result("b", False, 200)]
    report = format_report(results)
    assert "a" in report and "b" in report
    assert "1/2" in report  # 1 of 2 passed
    assert "300" in report  # total tokens summed


def test_format_report_marks_each_outcome():
    results = [_result("a", True), _result("b", False)]
    report = format_report(results)
    # A reader should be able to tell pass from fail at a glance.
    assert "PASS" in report
    assert "FAIL" in report
