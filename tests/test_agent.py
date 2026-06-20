import asyncio

import pytest

import agent
from provider import _chunk, _tc


class ScriptedLLM:
    """Test harness standing in for stream_response.

    Constructed with a list of "turns"; each turn is a list of pre-built
    chunks. Each call to the instance consumes the next turn and yields its
    chunks as an async generator — matching stream_response's signature.
    """

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


def test_streaming_text_accumulates(monkeypatch):
    """Text fragments from multiple chunks are joined into one assistant message."""
    turns = [
        [
            _chunk(content="one"),
            _chunk(content=", "),
            _chunk(content="two"),
            _chunk(content=", "),
            _chunk(content="three"),
            _chunk(finish_reason="stop"),
        ]
    ]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))

    messages = asyncio.run(agent.run_agent("count to three"))

    assistant = messages[1]
    assert assistant["role"] == "assistant"
    assert assistant["content"] == "one, two, three"
    assert "tool_calls" not in assistant


def test_streaming_carries_finish_reason_forward(monkeypatch):
    """finish_reason is carried forward from the single chunk that sets it."""
    turns = [
        [
            _chunk(content="a", finish_reason=None),
            _chunk(content="b", finish_reason=None),
            _chunk(content="c", finish_reason=None),
            _chunk(content="d", finish_reason=None),
            _chunk(content="e", finish_reason=None),
            _chunk(finish_reason="stop"),
        ]
    ]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))

    messages = asyncio.run(agent.run_agent("five letters"))

    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "abcde"


def test_streaming_empty_stream_terminates(monkeypatch):
    """An empty stream with no content chunks still terminates without error."""
    turns = [[_chunk(finish_reason="stop")]]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))

    messages = asyncio.run(agent.run_agent("say nothing"))

    assert len(messages) == 2
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] in (None, "")


def test_tool_call_then_stop(monkeypatch, tmp_path):
    """A read_file call executes and its content lands in a role:tool message."""
    target = tmp_path / "hello.txt"
    target.write_text("hello from the file")

    # Turn 1: model requests read_file with complete arguments.
    turn1 = [
        _chunk(
            tool_calls=[
                _tc(
                    0,
                    id="call_abc",
                    name="read_file",
                    arguments=f'{{"path": "{target}"}}',
                )
            ],
        ),
        _chunk(finish_reason="tool_calls"),
    ]
    # Turn 2: model summarizes and stops.
    turn2 = [
        _chunk(content="The file says: hello from the file."),
        _chunk(finish_reason="stop"),
    ]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM([turn1, turn2]))

    messages = asyncio.run(agent.run_agent("read hello.txt"))

    # Assistant turn 1 carries the tool_calls field.
    assistant1 = messages[1]
    assert assistant1["role"] == "assistant"
    assert assistant1["tool_calls"][0]["function"]["name"] == "read_file"
    # arguments stay as a JSON string, not a dict.
    assert isinstance(assistant1["tool_calls"][0]["function"]["arguments"], str)

    # A role:tool message follows with the file content.
    tool_msg = messages[2]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "call_abc"
    assert "hello from the file" in tool_msg["content"]

    # Final turn: model's summary.
    assert messages[-1]["content"] == "The file says: hello from the file."


@pytest.mark.asyncio
async def test_run_agent_returns_user_and_assistant(monkeypatch):
    """The loop should seed messages with the user turn and append exactly
    one assistant reply when the model streams plain text."""
    turns = [[_chunk(content="Hi! How can I help?"), _chunk(finish_reason="stop")]]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))

    history = await agent.run_agent("say hi")

    assert len(history) == 2
    assert history[0] == {"role": "user", "content": "say hi"}
    assert history[1] == {"role": "assistant", "content": "Hi! How can I help?"}
    assert not any(m["role"] == "tool" for m in history)


@pytest.mark.asyncio
async def test_run_agent_stops_after_text_reply(monkeypatch):
    """The loop must stop after a single text reply — no further calls."""
    call_count = 0

    class CountingLLM(ScriptedLLM):
        def __call__(self, messages, system_prompt):
            nonlocal call_count
            call_count += 1
            return super().__call__(messages, system_prompt)

    turns = [[_chunk(content="Done."), _chunk(finish_reason="stop")]]
    monkeypatch.setattr(agent, "stream_response", CountingLLM(turns))

    await agent.run_agent("do something")

    assert call_count == 1, f"Expected 1 model call, got {call_count}"


@pytest.mark.asyncio
async def test_run_agent_passes_full_history_to_model(monkeypatch):
    """Each call to the model should receive the full message history so far
    and a non-empty system prompt."""
    received_messages: list = []
    system_prompts: list = []
    call_count = 0

    class CapturingLLM(ScriptedLLM):
        def __call__(self, messages, system_prompt):
            nonlocal call_count
            call_count += 1
            received_messages.extend(messages)
            system_prompts.append(system_prompt)
            return super().__call__(messages, system_prompt)

    turns = [[_chunk(content="Response."), _chunk(finish_reason="stop")]]
    monkeypatch.setattr(agent, "stream_response", CapturingLLM(turns))

    await agent.run_agent("hello")

    # The model should have been called exactly once for a no-tool task.
    assert call_count == 1
    # The model should have received the user message as the first element.
    assert received_messages[0] == {"role": "user", "content": "hello"}
    # The system prompt must be a non-empty string on every call.
    assert all(isinstance(p, str) and p for p in system_prompts)
