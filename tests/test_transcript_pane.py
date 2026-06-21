"""BDD gate for Phase 10.2 — the transcript pane.

Scenario: TUI transcript pane renders streamed text
  Given the agent is launched with AGENT_UI=tui
  When the agent processes a task that produces streamed text
  Then text_delta events are routed to the TranscriptPane widget
  And the text visible in the transcript pane is identical to the
      assistant content that would appear in a stdout run
  And the final message history contains the same messages as a stdout run

The scenario is driven with Textual's Pilot test harness (run_test()), which
hosts the real AgentApp without a terminal. The agent is driven by the Phase 9
ScriptedLLM so the run is deterministic and needs no API key.
"""

import asyncio

import agent
import tui.emit
from provider import _chunk
from tui.app import AgentApp
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


def _text_only_turns():
    """A task that streams plain text across several chunks and stops."""
    return [
        [
            _chunk(content="The agent loop "),
            _chunk(content="reads a task, "),
            _chunk(content="calls the model, "),
            _chunk(content="and runs tools until done."),
            _chunk(finish_reason="stop"),
        ]
    ]


def _pane_text(app: AgentApp) -> str:
    """Reconstruct the visible transcript text from the RichLog's rendered lines."""
    pane = app.query_one(TranscriptPane)
    return "".join(strip.text for strip in pane.lines)


def test_append_text_renders_into_pane():
    """A direct append_text() call lands its content in the pane. Streamed text
    is line-buffered (committed on newline/turn end) so logical lines stay
    intact, so the fragment carries a trailing newline to complete the line."""

    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            app.query_one(TranscriptPane).append_text("hello pane\n")
            await pilot.pause()
            assert "hello pane" in _pane_text(app)

    asyncio.run(_run())


def test_text_delta_routed_to_pane(monkeypatch):
    """text_delta events emitted during a real agent run reach the pane, and the
    visible text equals the assistant content that a stdout run would produce."""
    turns = _text_only_turns()
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))
    # Bind the agent's emit to the TUI seam (renderer resolves to stdout by
    # default in tests because AGENT_UI is unset). This mirrors what running
    # with AGENT_UI=tui does at import time.
    monkeypatch.setattr(agent, "emit", tui.emit.emit)

    # The assistant content a stdout run would produce: the concatenated deltas.
    expected = "The agent loop reads a task, calls the model, and runs tools until done."

    async def _run():
        app = AgentApp("explain the agent loop")
        set_app(app)  # so renderer.emit (tui branch) routes into this app
        async with app.run_test() as pilot:
            # on_mount started run_agent as a Task; let it stream to completion.
            for _ in range(50):
                await pilot.pause()
                if expected in _pane_text(app):
                    break
            pane_text = _pane_text(app)
        return pane_text

    pane_text = asyncio.run(_run())
    # The pane shows exactly the streamed assistant content (no other text).
    assert pane_text == expected


def test_history_matches_stdout_run(monkeypatch):
    """The final message history from a TUI-driven run (the agent task launched
    by AgentApp.on_mount) is identical to a stdout run on the same turns."""
    # Stdout run.
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(_text_only_turns()))
    stdout_history = asyncio.run(agent.run_agent("explain the agent loop"))

    # TUI-driven run: the app's on_mount task drives run_agent and records the
    # final history on app.agent_history.
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(_text_only_turns()))
    captured: dict = {}

    async def _run():
        app = AgentApp("explain the agent loop")
        set_app(app)
        async with app.run_test() as pilot:
            # End the persistent steering loop so run_agent returns its history.
            app.request_shutdown()
            for _ in range(50):
                await pilot.pause()
                if app.agent_history is not None:
                    break
            captured["history"] = app.agent_history

    asyncio.run(_run())

    assert captured["history"] is not None
    assert captured["history"] == stdout_history
