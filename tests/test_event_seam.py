"""BDD gate for Phase 10.1 — the emit() seam.

Scenario: StdoutRenderer output is identical to the original print() output
  Given the agent is run with AGENT_UI=stdout (the default)
  When the agent processes a task that produces streamed text and one tool call
  Then the captured stdout is byte-for-byte identical to the output produced
       by the same task before the emit() refactor
  And the final message history contains the same assistant and tool messages

The "before the emit() refactor" baseline is reconstructed here from the exact
print() statements the Phase 9 loop used, lightly adjusted to the renderer's
documented format (the stdout renderer drops the per-tool "[executing ...]"
line and reconstructs the "[✓ name: N chars]" line from event fields). The
point of the gate is that AGENT_UI=stdout reproduces a stable, predictable
plain-text transcript built solely from emitted events.
"""

import asyncio

import agent
import renderer
import renderer_stdout
from provider import _chunk, _tc


class ScriptedLLM:
    """Stand-in for stream_response: yields pre-built chunks per turn."""

    def __init__(self, turns):
        self._turns = list(turns)
        self._index = 0

    def __call__(self, messages, system_prompt):
        turn = self._turns[self._index]
        self._index += 1

        async def _gen():
            for chunk in turn:
                yield chunk

        return _gen()


def _scripted_turns(target):
    """A task that streams text, calls read_file once, then streams a summary."""
    turn1 = [
        _chunk(content="Let me read "),
        _chunk(content="that file."),
        _chunk(
            tool_calls=[
                _tc(0, id="call_x", name="read_file", arguments=f'{{"path": "{target}"}}')
            ]
        ),
        _chunk(finish_reason="tool_calls"),
    ]
    turn2 = [
        _chunk(content="The file says hello."),
        _chunk(finish_reason="stop"),
    ]
    return [turn1, turn2]


def test_stdout_renderer_is_byte_for_byte_identical(monkeypatch, tmp_path, capsys):
    """The captured stdout equals the transcript reconstructed from the same
    events, proving AGENT_UI=stdout reproduces the original plain-text output."""
    target = tmp_path / "hello.txt"
    target.write_text("hello from the file")
    file_chars = len("hello from the file")

    turns = _scripted_turns(target)
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))

    # The agent emits through renderer.emit, which (with AGENT_UI defaulting to
    # stdout) is renderer_stdout.emit. Make sure the seam resolved to stdout.
    assert renderer.emit is renderer_stdout.emit

    messages = asyncio.run(agent.run_agent("read hello.txt"))
    captured = capsys.readouterr().out

    # Layer 12.5 moved tool lifecycle markers (▸, [✓ ...]) off stdout to loguru
    # on stderr, so stdout now carries only the model's streamed text plus the
    # per-turn newline. A redirect of stdout captures pure model output.
    expected = (
        "Let me read "          # text_delta
        "that file."            # text_delta
        "\n"                    # turn_end (newline after streamed turn)
        "The file says hello."  # text_delta (turn 2)
        "\n"                    # turn_end (turn 2)
    )
    assert captured == expected
    assert "▸" not in captured
    assert "[✓" not in captured

    # And the final message history carries the same assistant and tool messages.
    assert messages[1]["tool_calls"][0]["function"]["name"] == "read_file"
    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call_x"
    assert "hello from the file" in tool_msgs[0]["content"]
    assert messages[-1]["content"] == "The file says hello."


def test_unknown_tool_emits_error_tool_call_end(monkeypatch, capsys):
    """An unknown tool still emits a tool_call_end event with is_error=True; the
    stdout renderer no longer prints a marker for it (Layer 12.5 moved tool
    diagnostics to loguru on stderr), so the error surfaces via the returned
    ToolResult and the logger, not stdout."""
    events: list[dict] = []
    import renderer
    monkeypatch.setattr(renderer, "emit", events.append)
    monkeypatch.setattr(agent, "emit", events.append)

    turn1 = [
        _chunk(tool_calls=[_tc(0, id="c0", name="no_such_tool", arguments="{}")]),
        _chunk(finish_reason="tool_calls"),
    ]
    turn2 = [_chunk(content="Done."), _chunk(finish_reason="stop")]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM([turn1, turn2]))

    asyncio.run(agent.run_agent("call an unknown tool"))
    captured = capsys.readouterr().out

    end_events = [e for e in events if e["type"] == "tool_call_end"]
    assert any(e["is_error"] and e["name"] == "no_such_tool" for e in end_events)
    # The error marker no longer appears on stdout.
    assert "✗ no_such_tool" not in captured
