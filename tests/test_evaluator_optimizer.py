"""Behavior tests for the evaluator-optimizer (critic) architecture.

Call order: one reactive run for the initial answer, then alternating
critic / revision runs until the critic says PASS or the round cap is hit.
"""

import asyncio

import agent
import architectures  # noqa: F401 — registers the alternate architectures
from architecture import RunContext, get_architecture
from architectures.evaluator_optimizer import MAX_ROUNDS
from provider import _chunk


class ScriptedLLM:
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


def _text_turn(text: str):
    return [_chunk(content=text), _chunk(finish_reason="stop")]


def test_passes_first_try_returns_initial_answer(monkeypatch):
    turns = [
        _text_turn("good answer"),  # initial reactive run
        _text_turn("PASS"),  # critic approves
    ]
    scripted = ScriptedLLM(turns)
    monkeypatch.setattr(agent, "stream_response", scripted)

    arch = get_architecture("evaluator-optimizer")
    history = asyncio.run(arch.run("task", RunContext(system_prompt="sp")))

    assert scripted._index == 2  # initial + one critic call, no revision
    assert history[-1]["content"] == "good answer"


def test_revises_once_then_passes(monkeypatch):
    turns = [
        _text_turn("first answer"),  # initial
        _text_turn("needs work: be specific"),  # critic rejects
        _text_turn("second answer"),  # revised
        _text_turn("PASS"),  # critic approves
    ]
    scripted = ScriptedLLM(turns)
    monkeypatch.setattr(agent, "stream_response", scripted)

    arch = get_architecture("evaluator-optimizer")
    history = asyncio.run(arch.run("task", RunContext(system_prompt="sp")))

    assert scripted._index == 4
    assert history[-1]["content"] == "second answer"


def test_stops_at_round_cap_when_never_passing(monkeypatch):
    """The critic never approves; the loop stops after MAX_ROUNDS revisions and
    returns the last revision rather than looping forever."""
    turns = [_text_turn("answer 0")]
    for i in range(MAX_ROUNDS):
        turns.append(_text_turn("still not good"))  # critic rejects
        turns.append(_text_turn(f"answer {i + 1}"))  # revision
    scripted = ScriptedLLM(turns)
    monkeypatch.setattr(agent, "stream_response", scripted)

    arch = get_architecture("evaluator-optimizer")
    history = asyncio.run(arch.run("task", RunContext(system_prompt="sp")))

    # 1 initial + (critic + revision) * MAX_ROUNDS calls consumed.
    assert scripted._index == 1 + 2 * MAX_ROUNDS
    assert history[-1]["content"] == f"answer {MAX_ROUNDS}"
