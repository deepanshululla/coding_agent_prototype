"""HumanEval (164 Python function-completion problems) as coding Tasks.

The coding analogue of the GSM8K loader: a standard, field-comparable benchmark
fetched on demand. Each problem ships a function stub (signature + docstring) and
a hidden ``check(candidate)`` test; the agent completes the function in
``solution.py`` and is graded by running that check with :func:`pytest_grader`.

Split into a pure builder (:func:`build_humaneval_task`, unit-tested) and an
on-demand fetch (:func:`fetch_humaneval`, network — the dataset is a gzipped
JSONL in the official repo, read with stdlib ``gzip``, no extra dependency).
Use ``--limit`` to run a subset.
"""

from __future__ import annotations

import gzip
import json
import urllib.request
from pathlib import Path

from evals.graders import pytest_grader
from evals.harness import Task

HUMANEVAL_URL = "https://github.com/openai/human-eval/raw/master/data/HumanEval.jsonl.gz"
DEFAULT_CACHE = Path(__file__).resolve().parent.parent / ".cache" / "HumanEval.jsonl"

_PROMPT = (
    "Complete the function in solution.py so that the tests pass. The function "
    "signature and docstring are already there — implement the body. Edit "
    "solution.py only; do not modify any test file."
)


def build_humaneval_task(problem: dict) -> Task:
    """Turn one HumanEval problem dict into a pytest-graded coding Task.

    ``problem`` has ``task_id``, ``entry_point``, ``prompt`` (the stub), and
    ``test`` (defines ``check(candidate)``). The hidden test imports the entry
    point from the agent's solution and runs the problem's own ``check``.
    """
    entry = problem["entry_point"]
    stub = problem["prompt"]
    test = problem["test"]
    test_src = (
        f"from solution import {entry}\n\n{test}\n\ndef test_humaneval():\n    check({entry})\n"
    )
    return Task(
        id=problem["task_id"],
        prompt=_PROMPT,
        files={"solution.py": stub, "test_solution.py": test_src},
        grader=pytest_grader("test_solution.py"),
    )


def build_humaneval_tasks(problems: list[dict]) -> list[Task]:
    return [build_humaneval_task(p) for p in problems]


def fetch_humaneval(cache: Path = DEFAULT_CACHE) -> list[dict]:
    """Download (gunzip) and cache the HumanEval problems, returning parsed rows."""
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(HUMANEVAL_URL, timeout=30) as resp:
            cache.write_bytes(gzip.decompress(resp.read()))
    return [json.loads(line) for line in cache.read_text().splitlines() if line.strip()]


def load_humaneval(cache: Path = DEFAULT_CACHE) -> list[Task]:
    """Fetch HumanEval on demand and return all 164 coding Tasks."""
    return build_humaneval_tasks(fetch_humaneval(cache))
