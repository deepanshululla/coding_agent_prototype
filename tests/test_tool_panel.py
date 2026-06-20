"""Tests for Phase 10.3 — the tool panel.

Unit tests drive ToolPanel.add_tool_row / finish_tool_row / clear_rows directly
and assert on row_count and cell content. The BDD integration test drives a
full scripted agent run through AgentApp via Textual's Pilot and asserts the
panel reflects the tool_call_start / tool_call_end events.

Scenario: Tool panel shows spinner and resolves on completion
  Given the agent is launched with AGENT_UI=tui
  When the agent executes a tool call during a run
  Then a row appears in the ToolPanel with a spinner icon when tool_call_start fires
  And the row's icon changes to ✓ and shows a char count when tool_call_end
      fires with is_error=False
  And the row's icon changes to ✗ when tool_call_end fires with is_error=True
"""

import asyncio

import agent
from provider import _chunk, _tc
import tui.emit
from tui.app import AgentApp
from tui.components.tool_panel import ToolPanel
from tui.emit import set_app

from rich.text import Text


def _cell(panel: ToolPanel, index: int, column: str) -> str:
    """Return the plain text of a cell, regardless of str/Text storage."""
    value = panel.get_cell(str(index), column)
    return value.plain if isinstance(value, Text) else str(value)


# ── Unit tests: drive the widget methods directly ────────────────────────────


def test_add_tool_row_shows_spinner():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            panel = app.query_one(ToolPanel)
            panel.add_tool_row(0, "read_file")
            await pilot.pause()
            assert panel.row_count == 1
            assert _cell(panel, 0, "icon") == "⏳"
            assert _cell(panel, 0, "name") == "read_file"

    asyncio.run(_run())


def test_finish_tool_row_ok_shows_check_and_char_count():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            panel = app.query_one(ToolPanel)
            panel.add_tool_row(0, "read_file")
            panel.finish_tool_row(0, ok=True, chars=1234)
            await pilot.pause()
            assert _cell(panel, 0, "icon") == "✓"
            assert _cell(panel, 0, "detail") == "1,234c"

    asyncio.run(_run())


def test_finish_tool_row_error_shows_cross():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            panel = app.query_one(ToolPanel)
            panel.add_tool_row(0, "broken")
            panel.finish_tool_row(0, ok=False, chars=0)
            await pilot.pause()
            assert _cell(panel, 0, "icon") == "✗"
            assert _cell(panel, 0, "detail") == "err"

    asyncio.run(_run())


def test_finish_unknown_index_is_noop():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            panel = app.query_one(ToolPanel)
            panel.finish_tool_row(99, ok=True, chars=1)
            await pilot.pause()
            assert panel.row_count == 0

    asyncio.run(_run())


def test_clear_rows_resets_panel():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            panel = app.query_one(ToolPanel)
            panel.add_tool_row(0, "read_file")
            panel.add_tool_row(1, "write_file")
            await pilot.pause()
            assert panel.row_count == 2
            panel.clear_rows()
            await pilot.pause()
            assert panel.row_count == 0
            assert panel._rows == {}

    asyncio.run(_run())


# ── ScriptedLLM harness (mirrors test_transcript_pane) ───────────────────────


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
    """Turn 1 calls read_file on path; turn 2 streams a plain text reply."""
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


def test_tool_panel_resolves_ok_on_real_run(monkeypatch, tmp_path):
    """tool_call_start adds a spinner row; tool_call_end (success) resolves it
    to ✓ with a char count, driven by a real scripted agent run."""
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
            panel = app.query_one(ToolPanel)
            captured["row_count"] = panel.row_count
            captured["icon"] = _cell(panel, 0, "icon")
            captured["detail"] = _cell(panel, 0, "detail")

    asyncio.run(_run())

    assert captured["row_count"] == 1
    assert captured["icon"] == "✓"
    # "hello world" is 11 chars.
    assert captured["detail"] == "11c"


def test_tool_panel_resolves_error_on_real_run(monkeypatch):
    """tool_call_end with is_error=True resolves the row's icon to ✗."""
    turns = [
        [
            _chunk(tool_calls=[_tc(0, id="c0", name="no_such_tool", arguments="{}")]),
            _chunk(finish_reason="tool_calls"),
        ],
        [
            _chunk(content="done"),
            _chunk(finish_reason="stop"),
        ],
    ]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))
    monkeypatch.setattr(agent, "emit", tui.emit.emit)

    captured: dict = {}

    async def _run():
        app = AgentApp("call a missing tool")
        set_app(app)
        async with app.run_test() as pilot:
            for _ in range(80):
                await pilot.pause()
                if app.agent_history is not None:
                    break
            panel = app.query_one(ToolPanel)
            captured["icon"] = _cell(panel, 0, "icon")

    asyncio.run(_run())

    assert captured["icon"] == "✗"
