"""Tests for the HTML results report.

The report turns the accumulated JSONL run history into one self-contained HTML
file. Loading, summarizing, and rendering are all pure functions of the record
list, so they're tested directly with sample records — no browser, no run.
"""

import json

from evals.report_html import _runs_over_time, load_records, render_html, summarize

# Two runs of two models over the same two tasks.
RECORDS = [
    {
        "timestamp": "2026-06-21T10:00:00",
        "model": "claude",
        "task_id": "add",
        "passed": True,
        "total_tokens": 100,
        "duration_s": 1.0,
        "iterations": 1,
        "tool_calls": 2,
        "tool_errors": 0,
        "tool_unknown": 0,
        "detail": "ok",
    },
    {
        "timestamp": "2026-06-21T10:00:00",
        "model": "claude",
        "task_id": "fix",
        "passed": False,
        "total_tokens": 200,
        "duration_s": 2.0,
        "iterations": 3,
        "tool_calls": 5,
        "tool_errors": 2,
        "tool_unknown": 1,
        "detail": "tests failed",
    },
    {
        "timestamp": "2026-06-21T11:00:00",
        "model": "gpt",
        "task_id": "add",
        "passed": True,
        "total_tokens": 150,
        "duration_s": 1.5,
        "iterations": 1,
        "tool_calls": 1,
        "tool_errors": 0,
        "tool_unknown": 0,
        "detail": "ok",
    },
    {
        "timestamp": "2026-06-21T11:00:00",
        "model": "gpt",
        "task_id": "fix",
        "passed": True,
        "total_tokens": 250,
        "duration_s": 2.5,
        "iterations": 2,
        "tool_calls": 3,
        "tool_errors": 0,
        "tool_unknown": 0,
        "detail": "ok",
    },
]


# ── load_records ──────────────────────────────────────────────────────────────


def test_load_records_reads_jsonl(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in RECORDS) + "\n")
    got = load_records(path)
    assert len(got) == 4
    assert got[0]["task_id"] == "add"


def test_load_records_skips_blank_lines(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text(json.dumps(RECORDS[0]) + "\n\n  \n" + json.dumps(RECORDS[1]) + "\n")
    assert len(load_records(path)) == 2


# ── summarize ─────────────────────────────────────────────────────────────────


def test_summarize_overall_counts():
    s = summarize(RECORDS)
    assert s["total"] == 4
    assert s["passed"] == 3
    assert s["pass_rate"] == 0.75
    assert s["total_tokens"] == 700
    assert s["runs"] == 2  # two distinct (timestamp, model) runs


def test_summarize_per_model_sorted_by_pass_rate():
    s = summarize(RECORDS)
    models = s["by_model"]
    # gpt passed 2/2, claude 1/2 -> gpt ranks first.
    assert [m["model"] for m in models] == ["gpt", "claude"]
    gpt = models[0]
    assert gpt["passed"] == 2 and gpt["total"] == 2 and gpt["pass_rate"] == 1.0
    claude = models[1]
    assert claude["tool_errors"] == 2 and claude["tool_unknown"] == 1


# ── render_html ───────────────────────────────────────────────────────────────


def test_render_html_is_self_contained_document():
    html = render_html(RECORDS, title="My Evals", generated_at="2026-06-21")
    assert html.lstrip().startswith("<!DOCTYPE html")
    assert "<html" in html and "</html>" in html
    assert "<style" in html  # inline CSS, no external assets
    assert "My Evals" in html


def test_render_html_shows_every_task_and_verdict():
    html = render_html(RECORDS)
    for r in RECORDS:
        assert str(r["task_id"]) in html
    assert "PASS" in html and "FAIL" in html


def test_render_html_shows_models_and_overall_rate():
    html = render_html(RECORDS)
    assert "claude" in html and "gpt" in html
    assert "75" in html  # overall pass rate 75%


def test_render_html_escapes_detail_text():
    rec = dict(RECORDS[0], detail="<script>alert('x')</script>")
    html = render_html([rec])
    assert "<script>alert" not in html  # the raw tag must be escaped
    assert "&lt;script&gt;" in html


def test_render_html_handles_empty_records():
    html = render_html([])
    assert "<html" in html  # still a valid document, no crash


# ── trend charts ──────────────────────────────────────────────────────────────

# Two models, each with TWO runs over time, so a trend line has >1 point.
TREND_RECORDS = [
    # claude run 1 (1/2), run 2 (2/2)
    {
        "timestamp": "2026-06-21T09:00",
        "model": "claude",
        "task_id": "a",
        "passed": True,
        "total_tokens": 100,
    },
    {
        "timestamp": "2026-06-21T09:00",
        "model": "claude",
        "task_id": "b",
        "passed": False,
        "total_tokens": 100,
    },
    {
        "timestamp": "2026-06-22T09:00",
        "model": "claude",
        "task_id": "a",
        "passed": True,
        "total_tokens": 120,
    },
    {
        "timestamp": "2026-06-22T09:00",
        "model": "claude",
        "task_id": "b",
        "passed": True,
        "total_tokens": 120,
    },
    # gpt run 1 (2/2)
    {
        "timestamp": "2026-06-21T10:00",
        "model": "gpt",
        "task_id": "a",
        "passed": True,
        "total_tokens": 200,
    },
    {
        "timestamp": "2026-06-21T10:00",
        "model": "gpt",
        "task_id": "b",
        "passed": True,
        "total_tokens": 200,
    },
]


def test_runs_over_time_groups_by_model_and_run_sorted():
    series = _runs_over_time(TREND_RECORDS)
    assert set(series) == {"claude", "gpt"}
    claude = series["claude"]
    assert len(claude) == 2  # two runs
    assert [r["timestamp"] for r in claude] == sorted(r["timestamp"] for r in claude)
    assert claude[0]["pass_rate"] == 0.5  # run 1: 1/2
    assert claude[1]["pass_rate"] == 1.0  # run 2: 2/2
    assert claude[1]["tokens"] == 240  # 120 + 120


def test_render_html_includes_svg_trend_chart():
    html = render_html(TREND_RECORDS)
    assert "<svg" in html
    assert "<polyline" in html  # a trend line was drawn
    # both models appear in a chart legend / lines
    assert "claude" in html and "gpt" in html


def test_render_html_no_svg_when_empty():
    # No data -> no chart elements, but still a valid doc.
    assert "<svg" not in render_html([])
