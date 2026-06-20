"""Phase 17 — Extended Thinking.

The model may stream a reasoning scratchpad (delta.thinking) before its answer.
The agent must accumulate that into a thinking_buf and preserve it as a typed
``thinking`` content block — placed BEFORE the text block, with its signature
echoed verbatim — in the assistant message history, without printing the
scratchpad to normal stdout.

These tests are mock-driven (ScriptedLLM + scripted chunks). The live path
(litellm actually returning thinking deltas from a real Claude model with
THINKING_BUDGET > 0) is not exercised here — see the provider tests for the
kwargs wiring and the plan notes for the live caveat.
"""

import asyncio

import pytest

import agent
import provider
from provider import _chunk, _supports_thinking, _thinking_kwargs


class ScriptedLLM:
    """Stand-in for stream_response: yields pre-built chunks, one turn per call."""

    def __init__(self, turns):
        self._turns = list(turns)
        self._index = 0

    def __call__(self, messages, system_prompt, model=None):
        turn = self._turns[self._index]
        self._index += 1

        async def _gen():
            for chunk in turn:
                yield chunk

        return _gen()


def test_thinking_block_precedes_text_in_history(monkeypatch):
    """A delta.thinking stream becomes a typed thinking block before the text.

    BDD: Given the model streams reasoning then an answer, When the agent runs,
    Then the assistant message content is a list whose first block is the
    thinking block and second block is the text block.
    """
    turns = [
        [
            _chunk(thinking="step 1: plan"),
            _chunk(thinking=" the refactor"),
            _chunk(content="Here is the result"),
            _chunk(finish_reason="stop"),
        ]
    ]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))

    messages = asyncio.run(agent.run_agent("hard problem"))

    assistant = messages[1]
    assert assistant["role"] == "assistant"
    content = assistant["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "thinking"
    assert content[0]["thinking"] == "step 1: plan the refactor"
    assert content[1]["type"] == "text"
    assert content[1]["text"] == "Here is the result"


def test_thinking_signature_preserved_verbatim(monkeypatch):
    """The thinking block carries the signature verbatim for later replay."""
    turns = [
        [
            _chunk(thinking="reasoning", signature="sig-abc-123"),
            _chunk(content="answer"),
            _chunk(finish_reason="stop"),
        ]
    ]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))

    messages = asyncio.run(agent.run_agent("hard problem"))

    block = messages[1]["content"][0]
    assert block["type"] == "thinking"
    assert block["signature"] == "sig-abc-123"


def test_thinking_delta_emitted_not_on_stdout(monkeypatch, capsys):
    """Thinking is surfaced via a thinking_delta event, never plain stdout.

    The scratchpad must not leak into the visible answer. We assert a
    thinking_delta event is emitted and that the reasoning text is not printed
    to stdout by the loop.
    """
    events = []
    monkeypatch.setattr(agent, "emit", lambda e: events.append(e))

    turns = [
        [
            _chunk(thinking="secret reasoning"),
            _chunk(content="visible answer"),
            _chunk(finish_reason="stop"),
        ]
    ]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))

    asyncio.run(agent.run_agent("hard problem"))

    types = [e["type"] for e in events]
    assert "thinking_delta" in types
    thinking_event = next(e for e in events if e["type"] == "thinking_delta")
    assert thinking_event["delta"] == "secret reasoning"

    out = capsys.readouterr().out
    assert "secret reasoning" not in out


def test_no_thinking_keeps_plain_string_content(monkeypatch):
    """When the model does not reason, content stays a plain string (back-compat)."""
    turns = [
        [
            _chunk(content="just an answer"),
            _chunk(finish_reason="stop"),
        ]
    ]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))

    messages = asyncio.run(agent.run_agent("easy problem"))

    assert messages[1]["content"] == "just an answer"


def test_thinking_block_precedes_tool_calls(monkeypatch, tmp_path):
    """A thinking block is placed before content even on a tool-calling turn.

    The API requires thinking to precede text/tool_use. The assistant message
    must carry the thinking block in content AND the tool_calls structure.
    """
    from provider import _tc

    turns = [
        [
            _chunk(thinking="I should read the file"),
            _chunk(
                tool_calls=[
                    _tc(0, id="call_1", name="read_file", arguments='{"path": "x.txt"}')
                ]
            ),
            _chunk(finish_reason="tool_calls"),
        ],
        [
            _chunk(content="done"),
            _chunk(finish_reason="stop"),
        ],
    ]
    (tmp_path / "x.txt").write_text("file body")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))

    messages = asyncio.run(agent.run_agent("read x"))

    assistant = messages[1]
    assert assistant["role"] == "assistant"
    assert isinstance(assistant["content"], list)
    assert assistant["content"][0]["type"] == "thinking"
    assert "tool_calls" in assistant


# ── provider-level wiring (thinking kwargs + model guard) ────────────────────


def test_supports_thinking_marker_match():
    assert _supports_thinking("claude-sonnet-4-5")
    assert _supports_thinking("anthropic/claude-opus-4-1")
    assert _supports_thinking("claude-3-7-sonnet")
    assert not _supports_thinking("gpt-4o")
    assert not _supports_thinking("claude-3-5-haiku")


def test_thinking_kwargs_disabled_by_default(monkeypatch):
    """With THINKING_BUDGET == 0, no thinking param is sent — just max_tokens."""
    monkeypatch.setattr(provider, "THINKING_BUDGET", 0)
    kw = _thinking_kwargs("claude-sonnet-4-5")
    assert "thinking" not in kw
    assert kw["max_tokens"] == provider.MAX_TOKENS


def test_thinking_kwargs_enabled_bumps_max_tokens(monkeypatch):
    """THINKING_BUDGET > 0 on a supported model sends thinking + a bumped max_tokens.

    max_tokens must exceed budget_tokens; the floor is budget + 2000.
    """
    monkeypatch.setattr(provider, "THINKING_BUDGET", 8000)
    monkeypatch.setattr(provider, "MAX_TOKENS", 8096)
    kw = _thinking_kwargs("claude-sonnet-4-5")
    assert kw["thinking"] == {"type": "enabled", "budget_tokens": 8000}
    assert kw["max_tokens"] == 10000  # 8000 + 2000, above the 8096 floor
    assert kw["max_tokens"] > 8000


def test_thinking_kwargs_unsupported_model_stays_disabled(monkeypatch):
    """Even with a budget set, an unsupported model gets no thinking param."""
    monkeypatch.setattr(provider, "THINKING_BUDGET", 8000)
    kw = _thinking_kwargs("gpt-4o")
    assert "thinking" not in kw


@pytest.mark.asyncio
async def test_acompletion_receives_thinking_param(monkeypatch):
    """End-to-end: stream_response forwards the thinking param to litellm.

    BDD: Given THINKING_BUDGET=8000 and a supported model, When stream_response
    runs, Then litellm.acompletion is called with the thinking param.
    """
    monkeypatch.setattr(provider, "USE_CLAUDE_CLI", False)
    monkeypatch.setattr(provider, "THINKING_BUDGET", 8000)
    captured = {}

    async def fake_stream():
        yield _chunk(content="hi", finish_reason="stop")

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return fake_stream()

    monkeypatch.setattr(provider.litellm, "acompletion", fake_acompletion)

    async for _ in provider.stream_response(
        [{"role": "user", "content": "x"}], "sp", model="claude-sonnet-4-5"
    ):
        pass

    assert captured["thinking"] == {"type": "enabled", "budget_tokens": 8000}
    assert captured["max_tokens"] > 8000
