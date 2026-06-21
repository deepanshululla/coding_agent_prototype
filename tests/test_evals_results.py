"""Tests for JSONL run persistence.

Each eval run appends one JSON record per task to a results file, tagged with
the run's model and an ISO timestamp, so scores can be tracked across models and
over time. Appending (not overwriting) means a results file accumulates history.
"""

import json

from evals.harness import EvalResult
from evals.results import append_run


def _result(task_id, passed, tokens=100):
    return EvalResult(
        task_id=task_id, passed=passed, detail="ok", total_tokens=tokens, duration_s=0.5
    )


def test_append_run_writes_one_record_per_task(tmp_path):
    path = tmp_path / "results.jsonl"
    append_run(path, [_result("a", True), _result("b", False)], model="m", timestamp="T")
    lines = path.read_text().splitlines()
    assert len(lines) == 2


def test_records_carry_model_timestamp_and_verdict(tmp_path):
    path = tmp_path / "results.jsonl"
    append_run(path, [_result("a", True, 250)], model="gpt-4o", timestamp="2026-06-21T00:00:00")
    record = json.loads(path.read_text().splitlines()[0])
    assert record["task_id"] == "a"
    assert record["passed"] is True
    assert record["total_tokens"] == 250
    assert record["model"] == "gpt-4o"
    assert record["timestamp"] == "2026-06-21T00:00:00"


def test_append_run_appends_rather_than_overwrites(tmp_path):
    path = tmp_path / "results.jsonl"
    append_run(path, [_result("a", True)], model="m1", timestamp="T1")
    append_run(path, [_result("a", False)], model="m2", timestamp="T2")
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["model"] == "m1"
    assert json.loads(lines[1])["model"] == "m2"


def test_append_run_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "dir" / "results.jsonl"
    append_run(path, [_result("a", True)], model="m", timestamp="T")
    assert path.exists()
