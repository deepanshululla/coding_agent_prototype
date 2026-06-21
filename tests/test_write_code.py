"""Tests for the write_code delegation tool (dual-model Ollama: a reasoning
model drives the loop, a coding model does the edits via write_code).

See ADR-0015. The tool is only exposed when AGENT_CODE_MODEL is set; when it is,
write_code runs a focused reactive sub-agent on that model and returns its
summary. A contextvar guard stops the coding sub-agent from recursing into
write_code again.
"""

import asyncio

import agent
import config
import prompts
import tools


def run(coro):
    return asyncio.run(coro)


# ── schema gating ─────────────────────────────────────────────────────────────


def test_build_tools_schema_omits_write_code_without_code_model():
    schema = tools.build_tools_schema("")
    names = {entry["function"]["name"] for entry in schema}
    assert "write_code" not in names


def test_build_tools_schema_includes_write_code_with_code_model():
    schema = tools.build_tools_schema("ollama/qwen3-coder:30b")
    names = {entry["function"]["name"] for entry in schema}
    assert "write_code" in names


# ── disabled when unset ───────────────────────────────────────────────────────


def test_write_code_errors_when_code_model_unset(monkeypatch):
    monkeypatch.setattr(config, "CODE_MODEL", "")
    out = run(tools.write_code("add a docstring to foo()"))
    assert "Error" in out and "AGENT_CODE_MODEL" in out


# ── delegation ────────────────────────────────────────────────────────────────


def test_write_code_delegates_to_code_model(monkeypatch):
    monkeypatch.setattr(config, "CODE_MODEL", "ollama/qwen3-coder:30b")

    captured = {}

    async def fake_run_agent(task, **kwargs):
        captured["task"] = task
        captured["model"] = kwargs.get("model")
        captured["architecture"] = kwargs.get("architecture")
        return [
            {"role": "user", "content": task},
            {"role": "assistant", "content": "Edited foo.py: added a docstring."},
        ]

    monkeypatch.setattr(agent, "run_agent", fake_run_agent)

    out = run(tools.write_code("add a docstring to foo()", context="foo lives in foo.py"))

    assert captured["model"] == "ollama/qwen3-coder:30b"
    assert captured["architecture"] == "reactive"  # coder is a plain loop, not nested orchestration
    assert "add a docstring" in captured["task"]
    assert "foo.py" in captured["task"]  # context folded into the sub-task
    assert "Edited foo.py" in out  # the sub-agent's final summary is returned


def test_write_code_guards_against_recursion(monkeypatch):
    monkeypatch.setattr(config, "CODE_MODEL", "ollama/qwen3-coder:30b")

    # Simulate already running inside a write_code sub-agent.
    token = tools._in_write_code.set(True)
    try:
        out = run(tools.write_code("do something"))
    finally:
        tools._in_write_code.reset(token)

    assert "Error" in out
    assert "nested" in out.lower()


# ── prompt wiring ─────────────────────────────────────────────────────────────


def test_prompt_lists_write_code_when_delegating():
    p = prompts.build_system_prompt(delegate_coding=True, load_memories=False)
    assert "write_code" in p


def test_prompt_omits_write_code_when_not_delegating():
    p = prompts.build_system_prompt(delegate_coding=False, load_memories=False)
    assert "write_code" not in p
