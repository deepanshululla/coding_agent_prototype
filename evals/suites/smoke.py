"""A small smoke suite covering the three dimensions we chose to measure.

Each :class:`Task` is self-contained (no external repo, no network), so the
whole suite is cheap to run against a real model while still exercising the
parts that matter:

* ``add-function``  — code-writing correctness: write code that passes hidden
  tests (a HumanEval-flavoured, single-function gate).
* ``fix-bug``       — code correctness over an *edit*: the seed file is wrong;
  the agent must find and fix it so the seeded tests pass.
* ``count-lines``   — agent-loop / tool use: the answer requires driving the
  shell (bash/grep/find) to completion, not just emitting code.
"""

from evals.graders import command_grader, pytest_grader
from evals.harness import Task

SMOKE_SUITE: list[Task] = [
    Task(
        id="add-function",
        prompt=(
            "Create a file solution.py with a function `add(a, b)` that returns "
            "the sum of its two arguments. Do not edit any test files."
        ),
        files={
            "test_solution.py": (
                "from solution import add\n\n"
                "def test_add():\n"
                "    assert add(2, 3) == 5\n"
                "    assert add(-1, 1) == 0\n"
            ),
        },
        grader=pytest_grader("test_solution.py"),
    ),
    Task(
        id="fix-bug",
        prompt=(
            "The function in buggy.py is supposed to return the maximum of a list "
            "but returns the minimum. Fix it so the tests pass. Only edit buggy.py."
        ),
        files={
            "buggy.py": ("def biggest(xs):\n    return min(xs)\n"),
            "test_buggy.py": (
                "from buggy import biggest\n\n"
                "def test_biggest():\n"
                "    assert biggest([1, 5, 3]) == 5\n"
                "    assert biggest([-2, -9]) == -2\n"
            ),
        },
        grader=pytest_grader("test_buggy.py"),
    ),
    Task(
        id="count-lines",
        prompt=(
            "Count how many lines are in data.txt and write ONLY that number "
            "(as digits, no other text) to count.txt."
        ),
        files={"data.txt": "alpha\nbeta\ngamma\ndelta\n"},
        # The shell check both reads the agent's answer and verifies it: 4 lines.
        grader=command_grader('test "$(cat count.txt)" = "4"'),
    ),
]
