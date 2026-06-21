"""Tests for token-usage tracking that feeds the /usage command.

Usage flows: the provider attaches token counts to a chunk (litellm via
stream_options include_usage; the CLI fork by parsing the stream-json `result`
event). stream_turn captures that and folds a normalized usage dict into the
turn_end event. The TUI app accumulates per-turn usage into session_usage,
which /usage reports.
"""

import asyncio

import agent
import provider
from provider import _chunk
from tui.app import AgentApp


class ScriptedLLM:
    """Stand-in for stream_response: yields pre-built chunks per turn."""

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


# ── provider: usage plumbing ─────────────────────────────────────────────────


def test_litellm_call_requests_usage(monkeypatch):
    """The litellm path asks for streamed usage via stream_options."""
    monkeypatch.setattr(provider, "USE_CLAUDE_CLI", False)
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)

        async def _gen():
            yield _chunk(content="hi", finish_reason="stop")

        return _gen()

    monkeypatch.setattr(provider.litellm, "acompletion", fake_acompletion)

    async def _run():
        async for _ in provider.stream_response([{"role": "user", "content": "x"}], "sp"):
            pass

    asyncio.run(_run())
    assert captured.get("stream_options") == {"include_usage": True}


def test_parse_stream_json_line_extracts_usage_from_result():
    """The CLI fork's `result` event carries token usage we surface."""
    import json

    line = (
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "usage": {"input_tokens": 100, "output_tokens": 25},
            }
        )
        + "\n"
    ).encode()
    assert provider._parse_stream_json_line(line) == [
        {"kind": "usage", "prompt_tokens": 100, "completion_tokens": 25}
    ]


# ── agent: fold usage into turn_end ──────────────────────────────────────────


def test_turn_end_carries_usage(monkeypatch):
    """stream_turn reads chunk.usage and includes a normalized dict on turn_end."""
    events: list[dict] = []
    monkeypatch.setattr(agent, "emit", events.append)

    usage_obj = type("U", (), {"prompt_tokens": 30, "completion_tokens": 12, "total_tokens": 42})()
    turn = [
        _chunk(content="hello"),
        _chunk(finish_reason="stop", usage=usage_obj),
    ]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM([turn]))

    async def _run():
        await agent.stream_turn([{"role": "user", "content": "x"}], system_prompt="sp")

    asyncio.run(_run())
    turn_end = next(e for e in events if e["type"] == "turn_end")
    assert turn_end["usage"] == {
        "prompt_tokens": 30,
        "completion_tokens": 12,
        "total_tokens": 42,
    }


def test_turn_end_usage_none_when_absent(monkeypatch):
    """No usage reported → turn_end carries usage=None (CLI-fork text-only case)."""
    events: list[dict] = []
    monkeypatch.setattr(agent, "emit", events.append)
    turn = [_chunk(content="hi"), _chunk(finish_reason="stop")]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM([turn]))

    async def _run():
        await agent.stream_turn([{"role": "user", "content": "x"}], system_prompt="sp")

    asyncio.run(_run())
    turn_end = next(e for e in events if e["type"] == "turn_end")
    assert turn_end["usage"] is None


# ── app: accumulate usage across turns ───────────────────────────────────────


def test_app_accumulates_turn_usage():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            app.handle_agent_event(
                {
                    "type": "turn_end",
                    "iteration": 1,
                    "finish_reason": "tool_calls",
                    "tool_calls_count": 0,
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                }
            )
            app.handle_agent_event(
                {
                    "type": "turn_end",
                    "iteration": 2,
                    "finish_reason": "stop",
                    "tool_calls_count": 0,
                    "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
                }
            )
            await pilot.pause()
            assert app.session_usage["prompt_tokens"] == 150
            assert app.session_usage["completion_tokens"] == 30
            assert app.session_usage["total_tokens"] == 180

    asyncio.run(_run())
