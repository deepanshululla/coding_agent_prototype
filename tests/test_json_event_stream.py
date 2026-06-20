"""BDD gate for Phase 14.3 — JSON Event Stream.

Scenario: Piping AGENT_OUTPUT=json through jq shows all event types in order
  Given AGENT_OUTPUT=json is set in the environment
  And stream_response is mocked to return a stop chunk with text and one tool call
  When the agent is run and its stdout is captured line by line
  Then each line is a valid JSON object (json.loads succeeds)
  And the event types appear in this order:
       text_delta, tool_call_start, turn_end, tool_call_end, text_delta,
       turn_end, agent_end
       (the agent emits turn_end before dispatching the buffered tool calls,
        so tool_call_end follows turn_end within the first turn)
  And no text_delta event appears after the agent_end event
  And the tool_call_start event is followed (with possible text_deltas) by a
       tool_call_end event with the same tool_call_id

Renderer selects its emitter at import time from the env var. To re-resolve it
under a patched environment without ``importlib.reload`` corrupting module
identity for other modules that captured ``renderer.emit``, the test patches
the env, calls ``renderer._select_emit()``, and assigns the result onto both
``renderer.emit`` and ``agent.emit`` (the live references the loop calls),
restoring them in ``finally``.
"""

import asyncio
import json
import os
from unittest.mock import patch

import agent
import renderer
import renderer_stdout
from provider import _chunk, _tc


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


def _fake_stream_with_tool(target):
    """Turn 1 streams text + one tool call; turn 2 streams a summary."""
    turn1 = [
        _chunk(content="Reading."),
        _chunk(
            tool_calls=[
                _tc(0, id="call_x", name="read_file", arguments=f'{{"path": "{target}"}}')
            ]
        ),
        _chunk(finish_reason="tool_calls"),
    ]
    turn2 = [
        _chunk(content="Done."),
        _chunk(finish_reason="stop"),
    ]
    return [turn1, turn2]


def test_human_readable_lines_are_not_valid_json(monkeypatch, tmp_path, capsys):
    """RED half of the BDD gate: without AGENT_OUTPUT=json the stdout renderer
    prints human-readable text, so json.loads fails on a streamed delta line."""
    # Default renderer (stdout) is active in this process.
    assert renderer.emit is renderer_stdout.emit

    target = tmp_path / "hello.txt"
    target.write_text("hello from the file")
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(_fake_stream_with_tool(target)))

    asyncio.run(agent.run_agent("read hello.txt"))
    captured = capsys.readouterr().out

    first_line = captured.splitlines()[0]
    raised = False
    try:
        json.loads(first_line)
    except json.JSONDecodeError:
        raised = True
    assert raised, f"expected non-JSON human line, got parseable: {first_line!r}"


def test_json_output_emits_ndjson_in_order(tmp_path, capsys):
    """GREEN half: with AGENT_OUTPUT=json, every stdout line is a JSON object
    and the event types appear in the documented order."""
    target = tmp_path / "hello.txt"
    target.write_text("hello from the file")

    from sdk import run_agent_collecting

    saved_renderer_emit = renderer.emit
    saved_agent_emit = agent.emit
    with patch.dict(os.environ, {"AGENT_OUTPUT": "json"}):
        # Re-resolve the emitter under the patched env and install it on the
        # live references the loop reads (renderer.emit, agent.emit). No reload,
        # so other modules' captured references stay intact.
        json_emit = renderer._select_emit()
        renderer.emit = json_emit
        agent.emit = json_emit
        try:
            assert renderer.emit is renderer._json_emit
            assert renderer.emit is not renderer_stdout.emit

            with patch.object(agent, "stream_response", ScriptedLLM(_fake_stream_with_tool(target))):
                events, _messages = asyncio.run(run_agent_collecting("read hello.txt"))
        finally:
            renderer.emit = saved_renderer_emit
            agent.emit = saved_agent_emit

    captured = capsys.readouterr().out
    lines = [ln for ln in captured.splitlines() if ln.strip()]

    # Every stdout line is a valid JSON object.
    parsed = [json.loads(ln) for ln in lines]
    assert parsed, "expected at least one NDJSON line on stdout"
    assert all(isinstance(p, dict) for p in parsed)

    # The collected events (same order the NDJSON lines were printed) match the
    # actual emit sequence for this two-iteration run. The agent emits turn_end
    # at the end of the streaming loop, *before* it dispatches the buffered tool
    # calls — so tool_call_end lands after turn_end within the first turn:
    #   text_delta, tool_call_start, turn_end, tool_call_end,  (turn 1)
    #   text_delta, turn_end,                                  (turn 2)
    #   agent_end
    types = [e["type"] for e in events]
    assert types == [
        "text_delta",
        "tool_call_start",
        "turn_end",
        "tool_call_end",
        "text_delta",
        "turn_end",
        "agent_end",
    ]

    # agent_end is last; no text_delta appears after it.
    assert types[-1] == "agent_end"
    end_idx = types.index("agent_end")
    assert "text_delta" not in types[end_idx + 1 :]

    # tool_call_start precedes the matching tool_call_end with the same id.
    start_idx = next(
        i for i, e in enumerate(events)
        if e["type"] == "tool_call_start" and e["tool_call_id"] == "call_x"
    )
    end = next(
        i for i, e in enumerate(events)
        if e["type"] == "tool_call_end" and e["tool_call_id"] == "call_x"
    )
    assert start_idx < end

    # The NDJSON stdout lines carry the same ordered events.
    assert [p["type"] for p in parsed] == types
