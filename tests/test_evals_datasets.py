"""Tests for the large-N benchmark expansions: GSM8K + HumanEval loaders
(pure parsing/building, no network) and the generated planning tasks.

The download side of each loader is intentionally untested (it hits the network,
mirroring polyglot); the parse/build side is pure and fully covered here.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import evals.harness as harness
from evals.harness import run_task

# ── GSM8K ─────────────────────────────────────────────────────────────────────


def test_gsm8k_gold_answer_extraction():
    from evals.suites.gsm8k import gold_answer

    assert gold_answer("Janet has 3 apples...\n#### 18") == "18"
    assert gold_answer("...\n#### 1,000") == "1000"  # thousands comma stripped
    assert gold_answer("...\n#### -5") == "-5"


def test_gsm8k_build_tasks_are_answer_graded():
    from evals.suites.gsm8k import build_gsm8k_tasks

    rows = [
        {"question": "2+2?", "answer": "two plus two\n#### 4"},
        {"question": "3*3?", "answer": "three squared\n#### 9"},
    ]
    tasks = build_gsm8k_tasks(rows)
    assert len(tasks) == 2
    assert all(getattr(t.grader, "wants_answer", False) for t in tasks)
    # The gold number grades the answer: a reply ending in the number passes.
    assert tasks[0].grader("the answer is 4").passed
    assert not tasks[0].grader("the answer is 5").passed


# ── HumanEval ─────────────────────────────────────────────────────────────────


def _humaneval_problem():
    return {
        "task_id": "HumanEval/0",
        "entry_point": "add_one",
        "prompt": 'def add_one(x):\n    """Return x + 1."""\n',
        "test": (
            "def check(candidate):\n    assert candidate(1) == 2\n    assert candidate(10) == 11\n"
        ),
    }


def test_humaneval_build_task_shape():
    from evals.suites.humaneval import build_humaneval_task

    task = build_humaneval_task(_humaneval_problem())
    assert task.id == "HumanEval/0"
    assert "solution.py" in task.files and "add_one" in task.files["solution.py"]
    # The hidden test imports the entry point and runs the problem's check().
    test_src = task.files["test_solution.py"]
    assert "from solution import add_one" in test_src
    assert "def check(candidate)" in test_src


def test_humaneval_task_passes_with_correct_impl(monkeypatch, tmp_path):
    from evals.suites.humaneval import build_humaneval_task

    task = build_humaneval_task(_humaneval_problem())

    async def fake(t, **kwargs):
        Path("solution.py").write_text("def add_one(x):\n    return x + 1\n")
        return [{"type": "agent_end"}], []

    monkeypatch.setattr(harness, "run_agent_collecting", fake)
    assert asyncio.run(run_task(task)).passed is True


def test_humaneval_task_fails_with_wrong_impl(monkeypatch, tmp_path):
    from evals.suites.humaneval import build_humaneval_task

    task = build_humaneval_task(_humaneval_problem())

    async def fake(t, **kwargs):
        Path("solution.py").write_text("def add_one(x):\n    return x\n")
        return [{"type": "agent_end"}], []

    monkeypatch.setattr(harness, "run_agent_collecting", fake)
    assert asyncio.run(run_task(task)).passed is False


# ── generated planning tasks ──────────────────────────────────────────────────


def test_generated_planning_tasks_are_deterministic_and_valid():
    from evals.suites.planning import generate_planning_tasks

    a = generate_planning_tasks(20)
    b = generate_planning_tasks(20)
    assert len(a) == 20
    assert [t.id for t in a] == [t.id for t in b]  # deterministic (seeded)
    assert len({t.id for t in a}) == 20  # unique ids
    for t in a:
        assert getattr(t.grader, "wants_answer", False) is True

    # A correct topological order for a generated DAG must pass its grader.
    from evals.suites.planning import _GENERATED_SOLUTIONS  # id -> valid order

    t0 = a[0]
    plan = " -> ".join(_GENERATED_SOLUTIONS[t0.id])
    assert t0.grader(f"PLAN: {plan}").passed
