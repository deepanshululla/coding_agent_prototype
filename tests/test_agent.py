"""Integration tests for the agent loop with a mocked model.

We replace ``agent.stream_response`` with a scripted fake that yields canned OpenAI-format
chunks, so the loop logic is tested without any network call. This exercises the hard
parts: streaming accumulation, the stop check, parallel tool execution, and how tool
results land back in the message history.
"""

import asyncio
from types import SimpleNamespace

import agent


def _chunk(content=None, tool_calls=None, finish_reason=None):
    """Build one OpenAI-style streaming chunk."""
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


def _tc(index, id=None, name=None, arguments=None):
    """Build one tool-call fragment inside a delta."""
    fn = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=id, function=fn)


class ScriptedLLM:
    """Yields a different scripted turn (list of chunks) on each call."""

    def __init__(self, turns):
        self._turns = list(turns)

    def __call__(self, messages, system_prompt):
        chunks = self._turns.pop(0)

        async def _gen():
            for c in chunks:
                yield c

        return _gen()


def test_plain_text_turn_stops(monkeypatch):
    turns = [
        [
            _chunk(content="Hello, "),
            _chunk(content="world."),
            _chunk(finish_reason="stop"),
        ]
    ]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))

    messages = asyncio.run(agent.run_agent("say hi"))

    assert messages[0] == {"role": "user", "content": "say hi"}
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "Hello, world."
    assert "tool_calls" not in messages[1]
    # No tool was called.
    assert all(m["role"] != "tool" for m in messages)


def test_tool_call_then_stop(monkeypatch, tmp_path):
    (tmp_path / "marker.txt").write_text("x")

    # Turn 1: the model requests list_dir, with arguments split across two fragments.
    turn1 = [
        _chunk(
            tool_calls=[_tc(0, id="call_1", name="list_dir", arguments='{"path": ')],
        ),
        _chunk(
            tool_calls=[_tc(0, arguments=f'"{tmp_path}"' + "}")],
        ),
        _chunk(finish_reason="tool_calls"),
    ]
    # Turn 2: the model summarizes and stops.
    turn2 = [
        _chunk(content="Found marker.txt."),
        _chunk(finish_reason="stop"),
    ]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM([turn1, turn2]))

    messages = asyncio.run(agent.run_agent("list the dir"))

    # Assistant turn 1 carries the tool call; arguments stay a JSON string.
    assistant1 = messages[1]
    assert assistant1["role"] == "assistant"
    assert assistant1["tool_calls"][0]["function"]["name"] == "list_dir"
    assert isinstance(assistant1["tool_calls"][0]["function"]["arguments"], str)

    # A tool result message follows, addressed to the right call id.
    tool_msg = messages[2]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "call_1"
    assert "marker.txt" in tool_msg["content"]

    # Final assistant turn is the summary.
    assert messages[-1]["content"] == "Found marker.txt."


def test_multiple_parallel_tool_calls(monkeypatch, tmp_path):
    (tmp_path / "a.txt").write_text("aaa")
    (tmp_path / "b.txt").write_text("bbb")

    turn1 = [
        _chunk(
            tool_calls=[
                _tc(0, id="c0", name="read_file", arguments=f'{{"path": "{tmp_path / "a.txt"}"}}'),
                _tc(1, id="c1", name="read_file", arguments=f'{{"path": "{tmp_path / "b.txt"}"}}'),
            ]
        ),
        _chunk(finish_reason="tool_calls"),
    ]
    turn2 = [_chunk(content="done"), _chunk(finish_reason="stop")]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM([turn1, turn2]))

    messages = asyncio.run(agent.run_agent("read both"))

    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert {m["tool_call_id"] for m in tool_msgs} == {"c0", "c1"}
    contents = "".join(m["content"] for m in tool_msgs)
    assert "aaa" in contents and "bbb" in contents


def test_unknown_tool_is_reported_not_raised(monkeypatch):
    turn1 = [
        _chunk(tool_calls=[_tc(0, id="c0", name="no_such_tool", arguments="{}")]),
        _chunk(finish_reason="tool_calls"),
    ]
    turn2 = [_chunk(content="ok"), _chunk(finish_reason="stop")]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM([turn1, turn2]))

    messages = asyncio.run(agent.run_agent("call a bad tool"))

    tool_msg = next(m for m in messages if m["role"] == "tool")
    assert "Unknown tool" in tool_msg["content"]
