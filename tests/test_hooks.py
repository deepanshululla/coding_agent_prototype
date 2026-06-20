"""Tests for tool-call hooks (Phase 13.2): beforeToolCall / afterToolCall
plumbing in _execute_one_tool, and the ready-made hooks in src/hooks.py."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import agent
import hooks


def _read_call(path, *, id="c0"):
    """A parsed read_file tool call (read_file is auto-allowed by the policy)."""
    return {"id": id, "index": 0, "name": "read_file", "input": {"path": str(path)}}


@pytest.mark.asyncio
async def test_before_tool_call_fires_with_name_and_args(tmp_path):
    """before_tool_call is awaited and receives (name, args) for the call."""
    f = tmp_path / "a.txt"
    f.write_text("hello")
    seen = []

    async def spy(name, args):
        seen.append((name, args))
        return True

    result = await agent._execute_one_tool(_read_call(f), before_tool_call=spy)

    assert seen == [("read_file", {"path": str(f)})]
    assert result.is_error is False
    assert "hello" in result.content


@pytest.mark.asyncio
async def test_before_tool_call_returning_false_denies(tmp_path):
    """Returning False short-circuits to an error ToolResult; the tool never runs."""
    f = tmp_path / "secret.txt"
    f.write_text("do-not-read")
    ran = []

    async def deny(name, args):
        return False

    async def after(name, args, result):
        ran.append(result)  # would only run if the tool dispatched
        return result

    result = await agent._execute_one_tool(
        _read_call(f), before_tool_call=deny, after_tool_call=after
    )

    assert result.is_error is True
    assert "denied" in result.content.lower()
    assert "do-not-read" not in result.content
    assert ran == []  # after_tool_call never fired — tool was not dispatched


@pytest.mark.asyncio
async def test_before_tool_call_returning_none_proceeds(tmp_path):
    """A hook returning None (not False) does not deny — the call proceeds."""
    f = tmp_path / "a.txt"
    f.write_text("payload")

    async def noop(name, args):
        return None

    result = await agent._execute_one_tool(_read_call(f), before_tool_call=noop)

    assert result.is_error is False
    assert "payload" in result.content


@pytest.mark.asyncio
async def test_after_tool_call_receives_result_and_can_transform(tmp_path):
    """after_tool_call gets (name, args, result); its return value replaces it."""
    f = tmp_path / "a.txt"
    f.write_text("original")
    seen = []

    async def transform(name, args, result):
        seen.append((name, args, result))
        return "REDACTED"

    result = await agent._execute_one_tool(_read_call(f), after_tool_call=transform)

    assert len(seen) == 1
    assert seen[0][0] == "read_file"
    assert "original" in seen[0][2]
    assert result.content == "REDACTED"


@pytest.mark.asyncio
async def test_log_after_tool_call_writes_jsonl(tmp_path, monkeypatch):
    """log_after_tool_call appends one JSONL entry per call and returns result."""
    log_path = tmp_path / "tool-log.jsonl"
    monkeypatch.setattr(hooks, "LOG_PATH", log_path)

    out = await hooks.log_after_tool_call("read_file", {"path": "x.txt"}, "file body")

    assert out == "file body"  # pass-through unchanged
    lines = log_path.read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["tool"] == "read_file"
    assert entry["args"] == {"path": "x.txt"}
    assert entry["result_len"] == len("file body")
    assert entry["result_preview"] == "file body"
    assert "ts" in entry


@pytest.mark.asyncio
async def test_log_after_tool_call_appends(tmp_path, monkeypatch):
    """A second call appends rather than overwriting."""
    log_path = tmp_path / "tool-log.jsonl"
    monkeypatch.setattr(hooks, "LOG_PATH", log_path)

    await hooks.log_after_tool_call("read_file", {}, "a")
    await hooks.log_after_tool_call("list_dir", {}, "b")

    lines = log_path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["tool"] == "list_dir"


@pytest.mark.asyncio
async def test_confirm_before_tool_call_allows_readonly(monkeypatch):
    """Read-only tools pass the confirmation gate silently (no input prompt)."""
    def boom(*a, **k):  # input must NOT be called for read-only tools
        raise AssertionError("input() should not be called for read-only tools")

    monkeypatch.setattr("builtins.input", boom)
    assert await hooks.confirm_before_tool_call("read_file", {"path": "x"}) is True


@pytest.mark.asyncio
async def test_confirm_before_tool_call_prompts_for_write(monkeypatch):
    """Write/execute tools prompt; 'y' allows, anything else denies."""
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")
    assert await hooks.confirm_before_tool_call("write_file", {"path": "x"}) is True

    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")
    assert await hooks.confirm_before_tool_call("write_file", {"path": "x"}) is False


@pytest.mark.asyncio
async def test_hooks_thread_through_run_agent(monkeypatch, tmp_path):
    """before/after hooks reach the dispatch path via run_agent end-to-end."""
    from provider import _chunk, _tc

    f = tmp_path / "a.txt"
    f.write_text("content-from-file")
    recorded = []

    async def before(name, args):
        recorded.append(name)
        return True

    turn1 = [
        _chunk(tool_calls=[_tc(0, id="c0", name="read_file",
                               arguments=f'{{"path": "{f}"}}')]),
        _chunk(finish_reason="tool_calls"),
    ]
    turn2 = [_chunk(content="done"), _chunk(finish_reason="stop")]

    class ScriptedLLM:
        def __init__(self, turns):
            self._turns = list(turns)

        def __call__(self, *a, **k):
            turn = self._turns.pop(0)

            async def gen():
                for c in turn:
                    yield c

            return gen()

    monkeypatch.setattr(agent, "stream_response", ScriptedLLM([turn1, turn2]))

    messages = await agent.run_agent(
        "read a.txt", before_tool_call=before
    )

    assert "read_file" in recorded
    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert "content-from-file" in tool_msgs[0]["content"]
