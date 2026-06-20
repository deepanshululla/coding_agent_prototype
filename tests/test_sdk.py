"""BDD gate for Phase 14.1 — The SDK.

Scenario: SDK caller receives typed events in order with matching message history
  Given the agent is called via run_agent_collecting() with a simple task
  When the agent completes (no real API call — stream_response is mocked)
  Then the events list contains at least one text_delta event
  And the events list contains a tool_call_start followed by a tool_call_end
       for each tool call, in that order
  And the final event has type "agent_end" with status "ok"
  And the returned message history contains the same assistant turns and
       tool results that a direct run_agent() call would return
"""

import asyncio

import agent
import renderer
import renderer_stdout
from provider import _chunk, _tc
from sdk import run_agent_collecting


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


def test_collects_text_delta_and_agent_end(monkeypatch):
    """A plain text turn yields text_delta events ending with an ok agent_end."""
    turn = [
        _chunk(content="pong"),
        _chunk(finish_reason="stop"),
    ]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM([turn]))

    events, messages = asyncio.run(run_agent_collecting("ping"))

    assert any(e["type"] == "text_delta" for e in events)
    assert events[-1]["type"] == "agent_end"
    assert events[-1]["status"] == "ok"

    # message history: user turn + assistant turn
    assert messages[0] == {"role": "user", "content": "ping"}
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == "pong"


def test_collects_tool_call_start_before_end(monkeypatch, tmp_path):
    """Each tool call appears as a tool_call_start followed by a tool_call_end,
    and the tool result lands in the returned message history."""
    target = tmp_path / "hello.txt"
    target.write_text("hello from the file")

    turn1 = [
        _chunk(content="Reading."),
        _chunk(
            tool_calls=[_tc(0, id="call_x", name="read_file", arguments=f'{{"path": "{target}"}}')]
        ),
        _chunk(finish_reason="tool_calls"),
    ]
    turn2 = [
        _chunk(content="Done."),
        _chunk(finish_reason="stop"),
    ]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM([turn1, turn2]))

    events, messages = asyncio.run(run_agent_collecting("read hello.txt"))

    # tool_call_start precedes tool_call_end for call_x.
    start_idx = next(
        i
        for i, e in enumerate(events)
        if e["type"] == "tool_call_start" and e["tool_call_id"] == "call_x"
    )
    end_idx = next(
        i
        for i, e in enumerate(events)
        if e["type"] == "tool_call_end" and e["tool_call_id"] == "call_x"
    )
    assert start_idx < end_idx
    assert events[-1]["type"] == "agent_end"

    # The same tool result a direct run_agent() call would return.
    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call_x"
    assert "hello from the file" in tool_msgs[0]["content"]
    assert messages[1]["tool_calls"][0]["function"]["name"] == "read_file"


def test_restores_emit_after_call(monkeypatch):
    """The emit seam is restored after the call, even across multiple calls,
    so the SDK does not leak its collecting wrapper into the renderer."""
    before_renderer = renderer.emit
    before_agent = agent.emit

    turn = [_chunk(content="ok"), _chunk(finish_reason="stop")]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM([turn]))

    asyncio.run(run_agent_collecting("ping"))

    assert renderer.emit is before_renderer
    assert agent.emit is before_agent


def test_restores_emit_on_exception(monkeypatch):
    """If run_agent raises, the original emit is still restored (finally)."""
    before_renderer = renderer.emit
    before_agent = agent.emit

    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(agent, "stream_response", boom)

    try:
        asyncio.run(run_agent_collecting("ping"))
    except RuntimeError:
        pass

    assert renderer.emit is before_renderer
    assert agent.emit is before_agent
    # And the live stdout emitter is back in place.
    assert renderer.emit is renderer_stdout.emit
