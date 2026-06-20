"""Behavior tests for the planner-executor architecture.

Call order: one planning call emits the step list, then one reactive run per
step, executed in order with each step seeing earlier steps' results. The final
answer is the last step's result.
"""

import asyncio

import agent
import architectures  # noqa: F401 — registers the alternate architectures
from architecture import RunContext, get_architecture
from provider import _chunk


class ScriptedLLM:
    def __init__(self, turns):
        self._turns = list(turns)
        self._index = 0
        self.calls = []  # the `messages` passed to each call, for assertions

    def __call__(self, messages, system_prompt, model=None):
        self.calls.append(messages)
        turn = self._turns[self._index]
        self._index += 1

        async def _gen():
            for chunk in turn:
                yield chunk

        return _gen()


def _text_turn(text: str):
    return [_chunk(content=text), _chunk(finish_reason="stop")]


def test_plans_then_executes_steps_in_order(monkeypatch):
    turns = [
        _text_turn("1. gather data\n2. write report"),  # plan → two steps
        _text_turn("data gathered"),  # step 1
        _text_turn("report written"),  # step 2
    ]
    scripted = ScriptedLLM(turns)
    monkeypatch.setattr(agent, "stream_response", scripted)

    arch = get_architecture("planner-executor")
    history = asyncio.run(arch.run("produce a report", RunContext(system_prompt="sp")))

    assert scripted._index == 3  # plan + two steps
    # Final answer is the last step's result.
    assert history[-1]["content"] == "report written"
    # Step 2's prompt threads in step 1's result (dependent execution).
    step2_messages = scripted.calls[2]
    assert "data gathered" in step2_messages[0]["content"]


def test_empty_plan_falls_back_to_reactive(monkeypatch):
    turns = [
        _text_turn("   "),  # plan → nothing parseable
        _text_turn("reactive answer"),  # plain reactive run
    ]
    scripted = ScriptedLLM(turns)
    monkeypatch.setattr(agent, "stream_response", scripted)

    arch = get_architecture("planner-executor")
    history = asyncio.run(arch.run("t", RunContext(system_prompt="sp")))

    assert history[-1]["content"] == "reactive answer"
