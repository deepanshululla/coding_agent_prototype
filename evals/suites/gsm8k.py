"""GSM8K (grade-school math word problems) as answer-graded reasoning Tasks.

The reasoning analogue of polyglot: a large, standard, field-comparable benchmark
fetched on demand instead of hand-authored. GSM8K's test split is ~1.3k multi-step
arithmetic word problems, each with a gold numeric answer after a ``#### `` marker.
We build one answer-graded Task per problem (graded by :func:`exact_answer` on the
gold number), so any local model — including tool-less ones via the provider's
no-tools path — can be scored on multi-step reasoning at statistically useful N.

Split, like polyglot, into a pure builder (:func:`build_gsm8k_tasks`, unit-tested)
and an on-demand fetch (:func:`fetch_gsm8k`, network). Use ``--limit`` on the
runner to subsample for a quick pass.
"""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

from evals.graders import exact_answer
from evals.harness import Task

#: Raw test split from the official repo (no HF-datasets dependency needed).
GSM8K_TEST_URL = (
    "https://raw.githubusercontent.com/openai/grade-school-math/master/"
    "grade_school_math/data/test.jsonl"
)
DEFAULT_CACHE = Path(__file__).resolve().parent.parent / ".cache" / "gsm8k-test.jsonl"

_FORMAT = (
    " Reason step by step, then write the final answer ALONE on the last line — "
    "just the number, with no words, units, commas, or punctuation."
)


def gold_answer(answer: str) -> str:
    """Extract the gold numeric answer from a GSM8K ``answer`` field.

    The reference answer ends with ``#### <number>``; we take that number and
    drop thousands-separator commas so "1,000" compares equal to "1000".
    """
    match = re.search(r"####\s*(.+)", answer)
    raw = match.group(1).strip() if match else answer.strip()
    return raw.replace(",", "")


def build_gsm8k_tasks(rows: list[dict]) -> list[Task]:
    """Turn parsed GSM8K rows ({question, answer}) into answer-graded Tasks."""
    tasks: list[Task] = []
    for i, row in enumerate(rows):
        question = row.get("question", "").strip()
        if not question:
            continue
        tasks.append(
            Task(
                id=f"gsm8k/{i:04d}",
                prompt=question + _FORMAT,
                grader=exact_answer(gold_answer(row.get("answer", ""))),
            )
        )
    return tasks


def fetch_gsm8k(cache: Path = DEFAULT_CACHE) -> list[dict]:
    """Download (and cache) the GSM8K test split, returning the parsed rows."""
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(GSM8K_TEST_URL, timeout=30) as resp:
            cache.write_bytes(resp.read())
    return [json.loads(line) for line in cache.read_text().splitlines() if line.strip()]


def load_gsm8k(cache: Path = DEFAULT_CACHE) -> list[Task]:
    """Fetch GSM8K on demand and return the full list of reasoning Tasks."""
    return build_gsm8k_tasks(fetch_gsm8k(cache))
