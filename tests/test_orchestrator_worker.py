"""Behavior tests for the orchestrator-worker architecture.

The orchestrator makes three kinds of model call, in order: one to decompose the
task into subtasks, one reactive worker run per subtask, and one to synthesize
the final answer. A ScriptedLLM returns those turns in call order.
"""

import asyncio

import agent
import architectures  # noqa: F401 — registers the alternate architectures
from architecture import RunContext, get_architecture
from provider import _chunk


class ScriptedLLM:
    """Yields pre-built chunks per call, one scripted turn at a time."""

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


def test_orchestrator_decomposes_runs_workers_and_synthesizes(monkeypatch):
    turns = [
        _text_turn("1. analyze X\n2. fix Y"),  # decomposition → two subtasks
        _text_turn("did analyze X"),  # worker 1 (reactive, one turn)
        _text_turn("did fix Y"),  # worker 2
        _text_turn("final combined answer"),  # synthesis
    ]
    scripted = ScriptedLLM(turns)
    monkeypatch.setattr(agent, "stream_response", scripted)

    arch = get_architecture("orchestrator-worker")
    history = asyncio.run(arch.run("big task", RunContext(system_prompt="sp")))

    # All four scripted turns were consumed (decompose + 2 workers + synthesize).
    assert scripted._index == 4
    assert history[0] == {"role": "user", "content": "big task"}
    assert history[-1]["content"] == "final combined answer"


def test_orchestrator_depth_cap_falls_back_to_reactive(monkeypatch):
    """At/over the nesting cap the orchestrator stops decomposing and just runs
    the task reactively — a single model turn, no decomposition or synthesis."""
    scripted = ScriptedLLM([_text_turn("just one reactive answer")])
    monkeypatch.setattr(agent, "stream_response", scripted)

    arch = get_architecture("orchestrator-worker")
    history = asyncio.run(arch.run("t", RunContext(system_prompt="sp", depth=2)))

    assert scripted._index == 1  # one call only — reactive, no decompose/synth
    assert history[-1]["content"] == "just one reactive answer"


def test_orchestrator_empty_decomposition_falls_back_to_reactive(monkeypatch):
    """If decomposition yields no subtasks, fall back to a plain reactive run."""
    turns = [
        _text_turn("   "),  # decomposition → nothing parseable
        _text_turn("reactive fallback answer"),  # reactive run of the task
    ]
    scripted = ScriptedLLM(turns)
    monkeypatch.setattr(agent, "stream_response", scripted)

    arch = get_architecture("orchestrator-worker")
    history = asyncio.run(arch.run("t", RunContext(system_prompt="sp")))

    assert history[-1]["content"] == "reactive fallback answer"
