"""Tests for grading SWE-bench predictions with the official harness.

The Docker invocation itself is integration (it builds images and runs tests),
so these tests cover the deterministic seams around it: parsing the report JSON
the harness writes, and locating that report file. Both are pure and need no
Docker.
"""

import json
from pathlib import Path

from evals.swebench_grade import GradeReport, _eval_command, find_report, parse_report

# A report shaped like the one swebench's run_evaluation writes (schema v2).
SAMPLE_REPORT = {
    "total_instances": 300,
    "submitted_instances": 3,
    "completed_instances": 3,
    "resolved_instances": 2,
    "unresolved_instances": 1,
    "empty_patch_instances": 0,
    "error_instances": 0,
    "submitted_ids": ["pallets__flask-4045", "psf__requests-1", "django__django-9"],
    "resolved_ids": ["pallets__flask-4045", "psf__requests-1"],
    "unresolved_ids": ["django__django-9"],
    "error_ids": [],
    "schema_version": 2,
}


def test_parse_report_extracts_resolved_and_submitted():
    report = parse_report(SAMPLE_REPORT)
    assert isinstance(report, GradeReport)
    assert report.submitted == 3
    assert report.resolved == 2
    assert report.resolved_ids == ["pallets__flask-4045", "psf__requests-1"]
    assert report.unresolved_ids == ["django__django-9"]
    assert report.error_ids == []


def test_parse_report_resolved_rate():
    assert parse_report(SAMPLE_REPORT).resolved_rate == 2 / 3


def test_parse_report_rate_is_over_submitted_not_total_dataset():
    # The denominator must be the slice we submitted (3), not the full 300.
    assert parse_report(SAMPLE_REPORT).resolved_rate < 0.7


def test_parse_report_handles_zero_submitted():
    empty = {"submitted_instances": 0, "resolved_instances": 0}
    r = parse_report(empty)
    assert r.submitted == 0
    assert r.resolved_rate == 0.0


def test_parse_report_falls_back_to_id_list_lengths():
    # If the *_instances counts are absent, derive them from the id lists.
    report = {"submitted_ids": ["a", "b"], "resolved_ids": ["a"]}
    r = parse_report(report)
    assert r.submitted == 2
    assert r.resolved == 1


def test_find_report_locates_the_run_report(tmp_path: Path):
    # The harness writes "<model>.<run_id>.json" into the working directory.
    (tmp_path / "claude-opus.my-run.json").write_text(json.dumps(SAMPLE_REPORT))
    (tmp_path / "unrelated.json").write_text("{}")
    found = find_report("my-run", tmp_path)
    assert found is not None
    assert found.name == "claude-opus.my-run.json"


def test_find_report_missing_returns_none(tmp_path: Path):
    assert find_report("absent-run", tmp_path) is None


def test_eval_command_resolves_a_real_predictions_path(tmp_path: Path):
    preds = tmp_path / "preds.jsonl"
    preds.write_text("{}")
    cmd = _eval_command(preds, "r", "princeton-nlp/SWE-bench_Lite", ["a__b-1"], 2)
    i = cmd.index("--predictions_path")
    assert cmd[i + 1] == str(preds.resolve())  # absolute, so cwd-independence holds
    assert "--instance_ids" in cmd and "a__b-1" in cmd


def test_eval_command_passes_gold_sentinel_through_unresolved():
    # "gold" is a harness sentinel, not a file — it must NOT be turned into a path.
    cmd = _eval_command("gold", "r", "princeton-nlp/SWE-bench_Lite", None, 1)
    i = cmd.index("--predictions_path")
    assert cmd[i + 1] == "gold"
    assert "--instance_ids" not in cmd  # omitted when no ids given
