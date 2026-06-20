"""Tests for Phase 10.4 — input box & status bar.

Unit tests drive StatusBar.set_iteration / set_done / set_cancelled directly and
assert on the rendered label, and simulate an InputBox Enter press via Pilot to
assert InputBox.Submitted is posted and pending_messages is populated. The BDD
integration test drives a full scripted agent run through AgentApp and asserts
the status bar tracks turn_end and agent_end.

Scenario: Input box starts a run and status bar tracks iterations
  Given the agent is launched with AGENT_UI=tui
  When the user types a task into the input box and presses Enter
  Then the task text is pushed into pending_messages
  And run_agent begins a new inner-loop pass with that task
  And the status bar shows "iter N/30" after each turn_end event fires
  And the status bar shows "done" after the agent_end event fires
"""

import asyncio

import agent
from provider import _chunk, _tc
import tui.emit
from tui.app import AgentApp
from tui.components.input_box import InputBox
from tui.components.status_bar import StatusBar
from tui.emit import set_app

from rich.text import Text


def _status_text(bar: StatusBar) -> str:
    """Return the plain text last passed to StatusBar.update().

    Static stores the content on the name-mangled `_Static__content` attribute;
    we pass it a plain str, so reading it back gives the rendered label.
    """
    content = bar._Static__content
    return content.plain if isinstance(content, Text) else str(content)


# ── Unit tests: StatusBar update methods ─────────────────────────────────────


def test_status_bar_shows_iteration():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            bar = app.query_one(StatusBar)
            bar.set_iteration(3)
            await pilot.pause()
            assert "iter 3/30" in _status_text(bar)

    asyncio.run(_run())


def test_status_bar_shows_done():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            bar = app.query_one(StatusBar)
            bar.set_done(5)
            await pilot.pause()
            assert "done (5 iters)" in _status_text(bar)

    asyncio.run(_run())


def test_status_bar_shows_cancelled():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            bar = app.query_one(StatusBar)
            bar.set_cancelled()
            await pilot.pause()
            assert "cancelled" in _status_text(bar)

    asyncio.run(_run())


def test_status_bar_reads_agent_model_env(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "my-custom-model")

    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            bar = app.query_one(StatusBar)
            bar.set_iteration(1)
            await pilot.pause()
            assert "my-custom-model" in _status_text(bar)

    asyncio.run(_run())


# ── Unit test: InputBox Submitted on Enter ───────────────────────────────────


def test_input_box_enter_populates_pending():
    """Typing into the input box and pressing Enter pushes the text into
    pending_messages and clears the field."""
    pending: list[dict] = []

    async def _run():
        app = AgentApp("noop", pending)
        async with app.run_test() as pilot:
            box = app.query_one(InputBox)
            box.focus()
            await pilot.pause()
            box.value = "do the thing"
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(_run())

    assert pending == [{"role": "user", "content": "do the thing"}]


def test_input_box_whitespace_only_is_ignored():
    """Whitespace-only submissions are filtered out before posting."""
    pending: list[dict] = []

    async def _run():
        app = AgentApp("noop", pending)
        async with app.run_test() as pilot:
            box = app.query_one(InputBox)
            box.focus()
            await pilot.pause()
            box.value = "   "
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(_run())

    assert pending == []


# ── ScriptedLLM harness (mirrors test_tool_panel) ────────────────────────────


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


def _tool_then_text_turns(path: str):
    """Turn 1 calls read_file (one iteration); turn 2 streams plain text and stops
    — so the run advances the iteration counter and then ends."""
    return [
        [
            _chunk(tool_calls=[
                _tc(0, id="c0", name="read_file", arguments=f'{{"path": "{path}"}}')
            ]),
            _chunk(finish_reason="tool_calls"),
        ],
        [
            _chunk(content="done"),
            _chunk(finish_reason="stop"),
        ],
    ]


# ── BDD integration test: full run through AgentApp ──────────────────────────


def test_status_bar_tracks_iterations_and_done(monkeypatch, tmp_path):
    """During a scripted run the status bar advances on each turn_end and shows
    'done (N iters)' after agent_end."""
    target = tmp_path / "hello.txt"
    target.write_text("hello world")
    turns = _tool_then_text_turns(str(target))
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))
    monkeypatch.setattr(agent, "emit", tui.emit.emit)

    captured: dict = {}

    async def _run():
        app = AgentApp("read the file")
        set_app(app)
        async with app.run_test() as pilot:
            for _ in range(80):
                await pilot.pause()
                if app.agent_history is not None:
                    break
            captured["status"] = _status_text(app.query_one(StatusBar))

    asyncio.run(_run())

    # Two iterations: a tool turn then a text turn, ending the run.
    assert "done (2 iters)" in captured["status"]


def test_input_submitted_pushes_into_pending_during_run(monkeypatch, tmp_path):
    """A submission via the input box during a run lands in pending_messages,
    which is the same list run_agent received by reference."""
    target = tmp_path / "hello.txt"
    target.write_text("hello world")
    turns = _tool_then_text_turns(str(target))
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))
    monkeypatch.setattr(agent, "emit", tui.emit.emit)

    pending: list[dict] = []

    async def _run():
        app = AgentApp("read the file", pending)
        set_app(app)
        async with app.run_test() as pilot:
            box = app.query_one(InputBox)
            box.focus()
            await pilot.pause()
            box.value = "also list the files"
            await pilot.press("enter")
            await pilot.pause()
            for _ in range(80):
                await pilot.pause()
                if app.agent_history is not None:
                    break

    asyncio.run(_run())

    assert {"role": "user", "content": "also list the files"} in pending
