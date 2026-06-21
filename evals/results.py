"""Persist eval runs as JSONL so scores can be tracked over time and models.

One line per task per run, appended (never overwritten). Each record is the
flattened `EvalResult` plus the run's ``model`` and ``timestamp`` — enough to
chart pass-rate or token cost across models and across commits later.
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.harness import EvalResult


def result_to_record(result: EvalResult, *, model: str | None, timestamp: str) -> dict:
    """Flatten one `EvalResult` into the JSONL record schema (one source of truth).

    Shared by :func:`append_run` and the HTML report so both agree on field names.
    """
    return {
        "timestamp": timestamp,
        "model": model,
        "task_id": result.task_id,
        "passed": result.passed,
        "total_tokens": result.total_tokens,
        "duration_s": round(result.duration_s, 3),
        "detail": result.detail,
        "iterations": result.iterations,
        "tool_calls": result.tool_stats.calls,
        "tool_errors": result.tool_stats.errors,
        "tool_unknown": result.tool_stats.unknown,
    }


def append_run(
    path: Path,
    results: list[EvalResult],
    *,
    model: str | None,
    timestamp: str,
) -> None:
    """Append one JSON record per result to ``path`` (creating parents as needed)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        for r in results:
            record = result_to_record(r, model=model, timestamp=timestamp)
            fh.write(json.dumps(record) + "\n")
