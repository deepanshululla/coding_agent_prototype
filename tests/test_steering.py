"""Phase 15 — Steering.

BDD scenario:

  Scenario: Steering continues the agent without replaying prior tool calls
    Given the agent has completed a task using read_file and write_file
    When a follow-up message is injected via the steering API asking to run
      the tests
    Then the agent continues from where it left off
    And the prior read_file and write_file calls are not replayed
    And the agent executes a bash tool call for the test run

The steering channel is the injected ``get_steering_messages`` callable: the
caller (here a test fixture) returns one follow-up message after the first
``stop`` turn, then an empty list. The agent must resume — appending the new
turns after the prior ones — without re-executing the earlier read_file /
write_file calls.
"""

import pytest

import agent
from policy import PolicyEngine
from provider import _chunk, _tc


class ScriptedLLM:
    """Stand-in for stream_response: yields one scripted turn per call."""

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


@pytest.mark.asyncio
async def test_steering_continues_without_replaying_prior_tool_calls(monkeypatch, tmp_path):
    src = tmp_path / "source.txt"
    src.write_text("original content")
    dst = tmp_path / "copy.txt"

    # Phase 1, turn 1: read_file + write_file in one batch, then tool_calls.
    turn1 = [
        _chunk(
            tool_calls=[
                _tc(0, id="c_read", name="read_file", arguments=f'{{"path": "{src}"}}'),
                _tc(
                    1,
                    id="c_write",
                    name="write_file",
                    arguments=f'{{"path": "{dst}", "content": "copied"}}',
                ),
            ]
        ),
        _chunk(finish_reason="tool_calls"),
    ]
    # Phase 1, turn 2: the model is satisfied and stops.
    turn2 = [_chunk(content="Done copying the file."), _chunk(finish_reason="stop")]
    # Phase 2, turn 3 (after steering): the model runs the tests via bash.
    turn3 = [
        _chunk(
            tool_calls=[
                _tc(0, id="c_bash", name="bash", arguments='{"command": "echo ran-tests"}'),
            ]
        ),
        _chunk(finish_reason="tool_calls"),
    ]
    # Phase 2, turn 4: the model wraps up and stops for good.
    turn4 = [_chunk(content="Tests passed."), _chunk(finish_reason="stop")]

    monkeypatch.setattr(agent, "stream_response", ScriptedLLM([turn1, turn2, turn3, turn4]))
    # Allow every tool so the scripted bash run actually dispatches.
    monkeypatch.setattr(agent, "_policy", PolicyEngine(rules=[], default="allow"))

    # The steering API: inject one follow-up after the first stop, then nothing.
    injected = {"count": 0}

    async def get_steering_messages():
        if injected["count"] == 0:
            injected["count"] += 1
            return [{"role": "user", "content": "now run the tests"}]
        return []

    messages = await agent.run_agent(
        "copy source.txt to copy.txt",
        get_steering_messages=get_steering_messages,
    )

    # Collect the tool calls the model actually requested, in order.
    requested = [
        tc["function"]["name"]
        for m in messages
        if m["role"] == "assistant"
        for tc in m.get("tool_calls", [])
    ]

    # The prior read_file and write_file calls appear exactly once — not replayed.
    assert requested.count("read_file") == 1
    assert requested.count("write_file") == 1
    # A bash call appears, and it comes after the read/write pair.
    assert "bash" in requested
    assert requested.index("bash") > requested.index("write_file")

    # The steering message was woven into the history (continued, not restarted).
    assert any(m["role"] == "user" and m["content"] == "now run the tests" for m in messages)

    # The bash tool actually ran and its output landed in a role:tool message.
    bash_tool_msgs = [m for m in messages if m["role"] == "tool" and m["tool_call_id"] == "c_bash"]
    assert len(bash_tool_msgs) == 1
    assert "ran-tests" in bash_tool_msgs[0]["content"]


@pytest.mark.asyncio
async def test_empty_initial_task_waits_for_steering(monkeypatch):
    """An empty initial task (TUI launched idle) must not consume a model turn —
    the agent waits for the first steering message, then runs it as turn one."""
    # Only ONE turn is scripted; if the empty task wrongly called the model, the
    # second (real) call would IndexError. It must serve the steering message.
    turns = [[_chunk(content="handled"), _chunk(finish_reason="stop")]]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))

    injected = {"n": 0}

    async def get_steering_messages():
        if injected["n"] == 0:
            injected["n"] += 1
            return [{"role": "user", "content": "do the thing"}]
        return []

    messages = await agent.run_agent("", get_steering_messages=get_steering_messages)

    # No empty user turn was created; the first message is the steering one.
    assert messages[0] == {"role": "user", "content": "do the thing"}
    assert messages[-1]["content"] == "handled"


@pytest.mark.asyncio
async def test_no_steering_callable_runs_outer_loop_once(monkeypatch):
    """With no get_steering_messages, the outer loop runs exactly once."""
    turns = [[_chunk(content="hi"), _chunk(finish_reason="stop")]]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))

    messages = await agent.run_agent("say hi")

    assert len(messages) == 2
    assert messages[-1]["content"] == "hi"


@pytest.mark.asyncio
async def test_steering_empty_return_ends_run(monkeypatch):
    """A get_steering_messages that returns [] immediately ends the run."""
    calls = {"n": 0}
    turns = [[_chunk(content="done"), _chunk(finish_reason="stop")]]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))

    async def get_steering_messages():
        calls["n"] += 1
        return []

    messages = await agent.run_agent("do it", get_steering_messages=get_steering_messages)

    assert calls["n"] == 1  # polled once, returned nothing, loop ended
    assert len(messages) == 2
