"""Graders — decide whether the agent's output for a task is correct.

A grader is a callable ``(workdir: Path) -> GradeResult``. It inspects the
directory the agent left behind (files it wrote, plus any seed files) and
returns a verdict with a human-readable detail. Graders never touch the agent
or a model, so they are deterministic and cheap to test.

The three built-ins cover the dimensions we care about:

* :func:`pytest_grader`  — code-writing correctness (run the hidden tests).
* :func:`command_grader` — agent-loop / tool use (did a shell command succeed).
* :func:`file_contains`  — a quick structural check without running anything.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

#: A grader returns a verdict from either the working directory (the default) or
#: the run's final answer string (answer-graders, marked ``wants_answer=True``).
#: The harness picks which to pass; the signature is broad to cover both shapes.
Grader = Callable[..., "GradeResult"]


@dataclass(frozen=True)
class GradeResult:
    """The outcome of grading one task: did it pass, and why.

    ``artifact`` carries optional machine-readable output the grader produced —
    e.g. the candidate diff for a SWE-bench task — kept separate from the
    human-facing ``detail``.
    """

    passed: bool
    detail: str = ""
    artifact: str | None = None


def command_grader(cmd: str, expect_exit: int = 0) -> Grader:
    """Pass iff running ``cmd`` (via the shell) in the workdir exits as expected.

    The default ``expect_exit=0`` is the common case ("the command succeeded");
    pass a different code for graders that treat a specific failure as success.
    """

    def grade(workdir: Path) -> GradeResult:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=workdir,
            capture_output=True,
            text=True,
        )
        passed = proc.returncode == expect_exit
        if passed:
            detail = f"`{cmd}` exited {proc.returncode} as expected"
        else:
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-5:]
            detail = f"`{cmd}` exited {proc.returncode} (expected {expect_exit})\n" + "\n".join(
                tail
            )
        return GradeResult(passed, detail)

    return grade


def pytest_grader(test_file: str | None = None) -> Grader:
    """Pass iff pytest succeeds in the workdir.

    ``test_file`` narrows the run to a single file (the task's hidden test);
    when ``None`` pytest collects whatever is in the directory. Runs with the
    same interpreter that's driving the eval so the venv is inherited.
    """

    def grade(workdir: Path) -> GradeResult:
        cmd = [sys.executable, "-m", "pytest", "-q"]
        if test_file is not None:
            cmd.append(test_file)
        proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True)
        passed = proc.returncode == 0
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-8:])
        return GradeResult(passed, tail)

    return grade


def _normalize_answer(text: str) -> str:
    """Canonicalize a free-text answer for comparison.

    Casefold, collapse internal whitespace, strip surrounding whitespace and
    trailing sentence punctuation, and drop thousands-separator commas in numbers
    (so ``1,000`` matches ``1000``). Deterministic — no model involved.
    """
    cleaned = " ".join(text.split()).strip().casefold().rstrip(".!?")
    # Drop commas only between digits (thousands separators), not elsewhere.
    out = []
    for i, ch in enumerate(cleaned):
        if (
            ch == ","
            and 0 < i < len(cleaned) - 1
            and cleaned[i - 1].isdigit()
            and cleaned[i + 1].isdigit()
        ):
            continue
        out.append(ch)
    return "".join(out)


def exact_answer(expected: str, *, normalize: bool = True) -> Grader:
    """Pass iff the run's final answer matches ``expected`` (normalized).

    This is an *answer*-grader (``wants_answer=True``): the harness feeds it the
    model's final spoken answer, not the workdir. The match is forgiving of how
    the model frames the answer — it passes when the normalized ``expected`` is
    the last non-empty line, OR the last whitespace-delimited token of that line
    (so "The answer is 42", "42.", and a bare "42" all match "42") — while still
    being deterministic. Set ``normalize=False`` for a raw, case-sensitive match.
    """
    want = _normalize_answer(expected) if normalize else expected

    def grade(answer: str) -> GradeResult:
        lines = [ln for ln in (answer or "").splitlines() if ln.strip()]
        last = lines[-1] if lines else ""
        if normalize:
            last_norm = _normalize_answer(last)
            tokens = last_norm.split()
            hit = last_norm == want or (tokens and tokens[-1] == want)
        else:
            hit = last.strip() == want
        if hit:
            return GradeResult(True, f"answer matched {expected!r}")
        return GradeResult(False, f"expected {expected!r}, last line was {last.strip()!r}")

    grade.wants_answer = True  # ty: ignore[unresolved-attribute]
    return grade


def answer_contains(substring: str) -> Grader:
    """Pass iff the run's final answer contains ``substring`` (case-insensitive).

    An answer-grader (``wants_answer=True``) for the looser case where the answer
    need only appear somewhere in the model's reply, not as the final line.
    """
    needle = substring.casefold()

    def grade(answer: str) -> GradeResult:
        if needle in (answer or "").casefold():
            return GradeResult(True, f"answer contains {substring!r}")
        return GradeResult(False, f"answer is missing {substring!r}")

    grade.wants_answer = True  # ty: ignore[unresolved-attribute]
    return grade


def valid_ordering(required: list[str], before: list[tuple[str, str]]) -> Grader:
    """Answer-grader for planning: pass iff the reply is a valid ordered plan.

    Planning effectiveness is "did the model produce a correct ordered plan that
    respects every dependency", not "did it match one fixed answer" — a DAG has
    many valid topological orders, and all should pass. This grader parses the
    ordered steps out of the model's reply and checks two things: every step in
    ``required`` appears, and for each ``(x, y)`` in ``before`` step ``x`` is
    ordered ahead of step ``y``.

    Parsing is robust to reasoning prose: if the reply contains a ``PLAN:``
    marker, only the text after the *last* one is read (so step-by-step thinking
    above it doesn't pollute the order); otherwise the whole reply is used. Each
    step's position is its first word-boundary occurrence, so "retest" never
    satisfies the "test" step and numbered/arrow/comma list styles all work.
    """

    def grade(answer: str) -> GradeResult:
        text = answer or ""
        marker = text.lower().rfind("plan:")
        segment = text[marker + len("plan:") :] if marker != -1 else text

        pos: dict[str, int] = {}
        for step in required:
            match = re.search(rf"\b{re.escape(step)}\b", segment, re.IGNORECASE)
            if match:
                pos[step] = match.start()

        missing = [s for s in required if s not in pos]
        if missing:
            return GradeResult(False, f"plan is missing step(s): {', '.join(missing)}")

        for x, y in before:
            if pos[x] >= pos[y]:
                return GradeResult(False, f"constraint violated: {x!r} must come before {y!r}")

        return GradeResult(True, "valid plan: all steps present, all constraints respected")

    grade.wants_answer = True  # ty: ignore[unresolved-attribute]
    return grade


def file_contains(path: str, substring: str) -> Grader:
    """Pass iff ``path`` (relative to the workdir) exists and holds ``substring``."""

    def grade(workdir: Path) -> GradeResult:
        target = workdir / path
        if not target.exists():
            return GradeResult(False, f"{path} was not created")
        text = target.read_text()
        if substring in text:
            return GradeResult(True, f"{path} contains the expected text")
        return GradeResult(False, f"{path} is missing {substring!r}")

    return grade
