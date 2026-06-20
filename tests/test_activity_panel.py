"""Tests for the ActivityPanel — the persistent right-pane activity log.

The ActivityPanel replaces the old per-turn ToolPanel. It is a scrolling
chronological feed of *model calls* (turns) and *tool calls*, plus a one-shot
thinking indicator, with a session-totals header. Unlike the old panel it does
NOT clear between turns — activity accumulates across the whole run.

Unit tests drive the widget methods directly and assert on the log table's
cells and the totals header. The BDD integration test drives a full scripted
agent run through AgentApp via Textual's Pilot and asserts the panel reflects
the turn_start / tool_call_start / tool_call_end / turn_end events.

Scenario: Activity panel logs model and tool calls and keeps them across turns
  Given the agent is launched with AGENT_UI=tui
  When the agent streams a turn and executes a tool call
  Then a model-turn row appears on turn_start (spinner) and resolves to its
       finish reason on turn_end
  And a tool row appears on tool_call_start (spinner) and resolves to ✓ with a
      char count on tool_call_end
  And rows from earlier turns remain visible when a new turn begins
"""

import asyncio

from rich.text import Text

import agent
import tui.emit
from provider import _chunk, _tc
from tui.app import AgentApp
from tui.components.activity_panel import ActivityPanel
from tui.emit import set_app


def _cell(panel: ActivityPanel, key: str, column: str) -> str:
    """Return the plain text of a log cell, regardless of str/Text storage."""
    value = panel.log.get_cell(key, column)
    return value.plain if isinstance(value, Text) else str(value)


# ── Unit tests: drive the widget methods directly ────────────────────────────


def test_start_turn_adds_model_spinner_row():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            panel = app.query_one(ActivityPanel)
            panel.start_turn(1, "claude-sonnet-4-5")
            await pilot.pause()
            assert panel.log.row_count == 1
            assert _cell(panel, "t1", "icon") == "⏳"
            assert "turn 1" in _cell(panel, "t1", "label")

    asyncio.run(_run())


def test_end_turn_resolves_finish_reason():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            panel = app.query_one(ActivityPanel)
            panel.start_turn(1, "m")
            panel.end_turn(1, "stop", 0)
            await pilot.pause()
            assert _cell(panel, "t1", "icon") == "●"
            assert _cell(panel, "t1", "detail") == "stop"

    asyncio.run(_run())


def test_tool_row_lifecycle_ok():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            panel = app.query_one(ActivityPanel)
            panel.start_turn(1, "m")
            panel.add_tool(0, "read_file")
            await pilot.pause()
            assert _cell(panel, "t1-tool0", "icon") == "⏳"
            assert _cell(panel, "t1-tool0", "label") == "read_file"
            panel.finish_tool(0, ok=True, chars=1234)
            await pilot.pause()
            assert _cell(panel, "t1-tool0", "icon") == "✓"
            assert _cell(panel, "t1-tool0", "detail") == "1,234c"

    asyncio.run(_run())


def test_tool_row_error_shows_cross():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            panel = app.query_one(ActivityPanel)
            panel.start_turn(1, "m")
            panel.add_tool(0, "broken")
            panel.finish_tool(0, ok=False, chars=0)
            await pilot.pause()
            assert _cell(panel, "t1-tool0", "icon") == "✗"
            assert _cell(panel, "t1-tool0", "detail") == "err"

    asyncio.run(_run())


def test_thinking_row_added_once_per_turn():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            panel = app.query_one(ActivityPanel)
            panel.start_turn(1, "m")
            panel.note_thinking()
            panel.note_thinking()  # repeated deltas must not add a second row
            await pilot.pause()
            assert _cell(panel, "t1-think", "icon") == "💭"
            # one turn row + one thinking row, nothing duplicated
            assert panel.log.row_count == 2

    asyncio.run(_run())


def test_log_persists_across_turns():
    """The defining behavior: rows accumulate; a new turn does NOT clear them."""

    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            panel = app.query_one(ActivityPanel)
            panel.start_turn(1, "m")
            panel.add_tool(0, "read_file")
            panel.finish_tool(0, ok=True, chars=10)
            panel.end_turn(1, "tool_calls", 1)
            panel.start_turn(2, "m")  # reuses tool index 0 next turn
            panel.add_tool(0, "write_file")
            await pilot.pause()
            # Turn 1's rows are still present alongside turn 2's.
            assert _cell(panel, "t1", "label").endswith("turn 1")
            assert _cell(panel, "t1-tool0", "label") == "read_file"
            assert _cell(panel, "t2", "label").endswith("turn 2")
            assert _cell(panel, "t2-tool0", "label") == "write_file"
            assert panel.log.row_count == 4

    asyncio.run(_run())


def test_totals_count_model_and_tool_calls():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            panel = app.query_one(ActivityPanel)
            panel.start_turn(1, "m")
            panel.add_tool(0, "a")
            panel.add_tool(1, "b")
            panel.end_turn(1, "tool_calls", 2)
            panel.start_turn(2, "m")
            panel.add_tool(0, "c")
            await pilot.pause()
            assert "2 model" in panel.totals_text
            assert "3 tool" in panel.totals_text

    asyncio.run(_run())


# ── ScriptedLLM harness (mirrors test_transcript_pane) ───────────────────────


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


def _tool_then_text_turns(path: str):
    """Turn 1 calls read_file on path; turn 2 streams a plain text reply."""
    return [
        [
            _chunk(
                tool_calls=[_tc(0, id="c0", name="read_file", arguments=f'{{"path": "{path}"}}')]
            ),
            _chunk(finish_reason="tool_calls"),
        ],
        [
            _chunk(content="done"),
            _chunk(finish_reason="stop"),
        ],
    ]


# ── BDD integration test: full run through AgentApp ──────────────────────────


def test_activity_panel_logs_full_run(monkeypatch, tmp_path):
    """A real scripted run logs both turns plus the tool call, resolved, with
    nothing cleared between turns."""
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
            panel = app.query_one(ActivityPanel)
            captured["row_count"] = panel.log.row_count
            captured["tool_icon"] = _cell(panel, "t1-tool0", "icon")
            captured["tool_detail"] = _cell(panel, "t1-tool0", "detail")
            captured["turn1"] = _cell(panel, "t1", "icon")
            captured["turn2"] = _cell(panel, "t2", "icon")

    asyncio.run(_run())

    # turn 1 (model) + tool row + turn 2 (model) = 3 rows, none cleared.
    assert captured["row_count"] == 3
    assert captured["tool_icon"] == "✓"
    assert captured["tool_detail"] == "11c"  # "hello world" is 11 chars
    assert captured["turn1"] == "●"
    assert captured["turn2"] == "●"
