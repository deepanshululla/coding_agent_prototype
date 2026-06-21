"""Tests for the eval graders — pure functions, no model in the loop.

A grader is a callable ``(workdir: Path) -> GradeResult`` that inspects the
working directory the agent left behind and decides pass/fail with a human
detail string. Because they never touch the agent or a provider, they are the
cheapest, most deterministic part of the eval stack to test.
"""

from pathlib import Path

from evals.graders import GradeResult, command_grader, file_contains, pytest_grader


def test_command_grader_passes_on_zero_exit(tmp_path: Path):
    result = command_grader("true")(tmp_path)
    assert isinstance(result, GradeResult)
    assert result.passed is True


def test_command_grader_fails_on_nonzero_exit(tmp_path: Path):
    result = command_grader("false")(tmp_path)
    assert result.passed is False
    # The detail should carry the exit code so a human can see *why*.
    assert "1" in result.detail


def test_command_grader_runs_in_the_workdir(tmp_path: Path):
    (tmp_path / "marker.txt").write_text("hi")
    # `test -f` only passes if the command's cwd is the workdir.
    assert command_grader("test -f marker.txt")(tmp_path).passed is True


def test_command_grader_custom_expected_exit(tmp_path: Path):
    # Some graders want a specific nonzero code to count as success.
    assert command_grader("exit 3", expect_exit=3)(tmp_path).passed is True
    assert command_grader("exit 0", expect_exit=3)(tmp_path).passed is False


def test_file_contains_true(tmp_path: Path):
    (tmp_path / "solution.py").write_text("def add(a, b):\n    return a + b\n")
    assert file_contains("solution.py", "return a + b")(tmp_path).passed is True


def test_file_contains_false_when_missing_substring(tmp_path: Path):
    (tmp_path / "solution.py").write_text("def add(a, b): ...")
    assert file_contains("solution.py", "return a + b")(tmp_path).passed is False


def test_file_contains_false_when_file_absent(tmp_path: Path):
    result = file_contains("nope.py", "x")(tmp_path)
    assert result.passed is False
    assert "nope.py" in result.detail


def test_pytest_grader_passes_when_tests_pass(tmp_path: Path):
    (tmp_path / "solution.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "test_solution.py").write_text(
        "from solution import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
    assert pytest_grader()(tmp_path).passed is True


def test_pytest_grader_fails_when_tests_fail(tmp_path: Path):
    (tmp_path / "solution.py").write_text("def add(a, b):\n    return a - b\n")
    (tmp_path / "test_solution.py").write_text(
        "from solution import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
    assert pytest_grader()(tmp_path).passed is False
