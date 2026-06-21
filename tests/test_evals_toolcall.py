"""Tests for the tool-calling eval: per-run tool metrics, model discovery,
the toolcall suite, and the multi-model comparison report.

All deterministic — no model calls. The harness's tool_stats() is a pure
function of the collected events; model discovery is a pure function of the
/api/tags JSON; the comparison formatter is a pure function of results.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import evals.harness as harness
from evals.harness import EvalResult, Task, run_task, tool_stats
from evals.models import chat_models
from evals.suites.toolcall import TOOLCALL_SUITE

# ── tool_stats: derive tool-calling quality from the event stream ─────────────


def test_tool_stats_counts_calls_errors_and_unknown():
    events = [
        {"type": "tool_call_start", "name": "read_file"},
        {"type": "tool_call_end", "name": "read_file", "is_error": False, "content": "ok"},
        {"type": "tool_call_start", "name": "open_file"},  # hallucinated
        {
            "type": "tool_call_end",
            "name": "open_file",
            "is_error": True,
            "content": "Unknown tool: open_file",
        },
        {"type": "tool_call_start", "name": "read_file"},
        {
            "type": "tool_call_end",
            "name": "read_file",
            "is_error": True,
            "content": "Error: bad arg",
        },
        {"type": "turn_end", "usage": {"total_tokens": 5}},
    ]
    s = tool_stats(events)
    assert s.calls == 3
    assert s.errors == 2
    assert s.unknown == 1
    assert round(s.error_rate, 2) == 0.67


def test_tool_stats_empty_is_zero():
    s = tool_stats([{"type": "agent_end"}])
    assert s.calls == 0 and s.errors == 0 and s.unknown == 0
    assert s.error_rate == 0.0


def test_run_task_populates_tool_stats(monkeypatch, tmp_path):
    async def fake(task, **kwargs):
        Path("out.txt").write_text("x")
        return (
            [
                {"type": "tool_call_start", "name": "write_file"},
                {"type": "tool_call_end", "name": "write_file", "is_error": False, "content": "ok"},
                {"type": "tool_call_start", "name": "frob"},
                {
                    "type": "tool_call_end",
                    "name": "frob",
                    "is_error": True,
                    "content": "Unknown tool: frob",
                },
                {"type": "agent_end"},
            ],
            [],
        )

    monkeypatch.setattr(harness, "run_agent_collecting", fake)
    from evals.graders import file_contains

    task = Task(id="t", prompt="p", grader=file_contains("out.txt", "x"))
    result = asyncio.run(run_task(task))
    assert isinstance(result, EvalResult)
    assert result.tool_stats.calls == 2
    assert result.tool_stats.errors == 1
    assert result.tool_stats.unknown == 1


# ── ollama model discovery ────────────────────────────────────────────────────


def test_chat_models_filters_embeddings_and_prefixes():
    tags = {
        "models": [
            {"name": "qwen3-coder:30b"},
            {"name": "gpt-oss:20b"},
            {"name": "nomic-embed-text:latest"},
            {"name": "bge-m3:latest"},
        ]
    }
    got = chat_models(tags)
    assert got == ["ollama_chat/gpt-oss:20b", "ollama_chat/qwen3-coder:30b"]


def test_chat_models_keeps_existing_prefix_and_dedupes():
    tags = {"models": [{"name": "ollama_chat/gpt-oss:20b"}, {"name": "gpt-oss:20b"}]}
    assert chat_models(tags) == ["ollama_chat/gpt-oss:20b"]


def test_chat_models_handles_empty():
    assert chat_models({}) == []
    assert chat_models({"models": []}) == []


# ── the toolcall suite ────────────────────────────────────────────────────────


def test_toolcall_suite_is_nonempty_and_well_formed():
    assert len(TOOLCALL_SUITE) >= 5
    ids = [t.id for t in TOOLCALL_SUITE]
    assert len(ids) == len(set(ids))  # unique ids
    for t in TOOLCALL_SUITE:
        assert t.prompt.strip()
        assert callable(t.grader)


# ── multi-model comparison report ─────────────────────────────────────────────


def _res(task_id, passed, calls, errors, unknown, tokens=10, dur=1.0):
    from evals.harness import ToolStats

    return EvalResult(
        task_id=task_id,
        passed=passed,
        detail="",
        total_tokens=tokens,
        duration_s=dur,
        tool_stats=ToolStats(calls, errors, unknown),
    )


def test_format_comparison_ranks_models_by_pass_rate():
    from evals.run import format_comparison

    by_model = {
        "ollama_chat/gpt-oss:20b": [_res("a", False, 5, 3, 2), _res("b", True, 2, 0, 0)],
        "ollama_chat/qwen3-coder:30b": [_res("a", True, 1, 0, 0), _res("b", True, 1, 0, 0)],
    }
    report = format_comparison(by_model)
    # Both models named, pass counts shown, and the clean model's totals appear.
    assert "qwen3-coder:30b" in report and "gpt-oss:20b" in report
    assert "2/2" in report  # qwen passed both
    assert "1/2" in report  # gpt-oss passed one
    # Tool-error and unknown-tool columns are surfaced.
    assert "unknown" in report.lower() or "unk" in report.lower()
