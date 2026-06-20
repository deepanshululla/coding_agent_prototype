"""Tests for the TUI steering loop and agent-error surfacing.

These cover two bugs found when the TUI appeared to "do nothing":

  1. Steering: after the initial task finished, follow-up messages typed into
     the input box went nowhere because AgentApp never wired
     get_steering_messages into run_agent. Now the input box feeds a steering
     queue that continues the run.

  2. Error surfacing: on_mount ran the agent in a fire-and-forget task with no
     exception handler, so a crash (e.g. a missing API key) vanished silently
     and the UI looked frozen. Now failures emit an agent_error event that the
     transcript and status bar render.

Driven with Textual's Pilot harness (run_test()), which hosts the real
AgentApp without a terminal. Scripted turns keep runs deterministic and
key-free.
"""

import asyncio

from rich.text import Text

import agent
import tui.emit
from provider import _chunk
from tui.app import AgentApp
from tui.components.input_box import InputBox
from tui.components.status_bar import StatusBar
from tui.components.transcript import TranscriptPane
from tui.emit import set_app


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


def _pane_text(app: AgentApp) -> str:
    pane = app.query_one(TranscriptPane)
    return "".join(strip.text for strip in pane.lines)


def _status_text(bar: StatusBar) -> str:
    content = bar._Static__content  # ty: ignore[unresolved-attribute]
    return content.plain if isinstance(content, Text) else str(content)


# ── Steering: input box drives get_steering ──────────────────────────────────


def test_input_box_resolves_get_steering():
    """A message submitted into the input box resolves the app's steering
    callable with that message."""

    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            waiter = asyncio.create_task(app._get_steering())
            await pilot.pause()
            box = app.query_one(InputBox)
            box.focus()
            box.value = "do more"
            await pilot.press("enter")
            await pilot.pause()
            result = await asyncio.wait_for(waiter, timeout=2)
            assert result == [{"role": "user", "content": "do more"}]

    asyncio.run(_run())


def test_steering_continues_the_run_with_a_followup(monkeypatch):
    """After the initial task ends, a follow-up typed into the input box drives
    a second turn — both answers land in the transcript."""
    turns = [
        [_chunk(content="first answer"), _chunk(finish_reason="stop")],
        [_chunk(content="second answer"), _chunk(finish_reason="stop")],
    ]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))
    monkeypatch.setattr(agent, "emit", tui.emit.emit)

    async def _run():
        app = AgentApp("initial task")
        set_app(app)
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause()
                if "first answer" in _pane_text(app):
                    break
            box = app.query_one(InputBox)
            box.focus()
            box.value = "now do the follow-up"
            await pilot.press("enter")
            for _ in range(50):
                await pilot.pause()
                if "second answer" in _pane_text(app):
                    break
            return _pane_text(app)

    text = asyncio.run(_run())
    assert "first answer" in text
    assert "second answer" in text
    assert "> now do the follow-up" in text


def test_shutdown_ends_the_run(monkeypatch):
    """request_shutdown makes the steering poll return [], so run_agent breaks
    out of the outer loop and records the final history."""
    turns = [[_chunk(content="all done"), _chunk(finish_reason="stop")]]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))
    monkeypatch.setattr(agent, "emit", tui.emit.emit)

    captured: dict = {}

    async def _run():
        app = AgentApp("one shot")
        set_app(app)
        async with app.run_test() as pilot:
            app.request_shutdown()
            for _ in range(80):
                await pilot.pause()
                if app.agent_history is not None:
                    break
            captured["history"] = app.agent_history

    asyncio.run(_run())
    assert captured["history"] is not None
    assert captured["history"][-1]["content"] == "all done"


# ── Error surfacing ──────────────────────────────────────────────────────────


def test_agent_error_surfaces_to_transcript_and_status(monkeypatch):
    """When the agent run raises, the failure is shown in the transcript and the
    status bar rather than being swallowed."""

    async def boom(*args, **kwargs):
        raise RuntimeError("Missing Anthropic API Key")

    monkeypatch.setattr(agent, "run_agent", boom)

    captured: dict = {}

    async def _run():
        app = AgentApp("anything")
        set_app(app)
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause()
                if "Missing Anthropic API Key" in _pane_text(app):
                    break
            captured["pane"] = _pane_text(app)
            captured["status"] = _status_text(app.query_one(StatusBar))

    asyncio.run(_run())
    assert "Missing Anthropic API Key" in captured["pane"]
    assert "error" in captured["status"].lower()
