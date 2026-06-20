"""BDD gate for Phase 10.5 — keybindings & themes.

Unit tests cover get_theme (named lookup + dark fallback) and the cooperative
cancel inside run_agent (cancel_event set → inner loop breaks and emits
agent_cancelled). The integration test drives AgentApp through Textual's Pilot
and asserts the Vim-style mode transitions and that AGENT_THEME wires the theme
dict into the widgets.

Scenario: Vim-style modal keybindings and theme env var changes colors
  Given the agent is launched with AGENT_UI=tui and the app starts in NORMAL mode
  When the user presses `j` then `k`
  Then the transcript scrolls down then up
  And pressing `i` switches to INSERT mode and focuses the input box
  And typing a follow-up message then pressing Enter queues a steering message
      and returns to NORMAL mode
  And pressing Ctrl-C during a run cancels the in-flight turn and the status bar
      shows "cancelled"
  And setting AGENT_THEME=light changes the ToolPanel "tool_ok" color to the
      light theme value
  And setting AGENT_THEME=light changes the StatusBar "status" color to the
      light theme value
"""

import asyncio

from rich.text import Text

import agent
from provider import _chunk, _tc
from tui.app import AgentApp
from tui.components.input_box import InputBox
from tui.components.status_bar import StatusBar
from tui.components.tool_panel import ToolPanel
from tui.emit import set_app
from tui.themes import THEMES, get_theme

# ── Unit tests: get_theme ────────────────────────────────────────────────────


def test_get_theme_dark_tool_ok():
    assert get_theme("dark")["tool_ok"] == "bright_green"


def test_get_theme_light_differs_from_dark():
    assert get_theme("light")["tool_ok"] == "dark_green"
    assert get_theme("light")["status"] == "grey50"


def test_get_theme_unknown_falls_back_to_dark(capsys):
    result = get_theme("does_not_exist")
    assert result is THEMES["dark"]
    err = capsys.readouterr().err
    assert "does_not_exist" in err


# ── Unit test: cooperative cancel inside run_agent ───────────────────────────


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


def test_cancel_event_stops_inner_loop_and_emits_cancelled(monkeypatch, tmp_path):
    """A pre-set cancel_event makes run_agent break the inner loop on the first
    pass, emitting agent_cancelled and never calling the model."""
    target = tmp_path / "hello.txt"
    target.write_text("hello world")

    call_count = 0

    class CountingLLM(ScriptedLLM):
        def __call__(self, messages, system_prompt, model=None):
            nonlocal call_count
            call_count += 1
            return super().__call__(messages, system_prompt)

    monkeypatch.setattr(agent, "stream_response", CountingLLM(_tool_then_text_turns(str(target))))

    events: list[dict] = []
    monkeypatch.setattr(agent, "emit", events.append)

    cancel = asyncio.Event()
    cancel.set()

    asyncio.run(agent.run_agent("read the file", None, cancel))

    assert {"type": "agent_cancelled"} in events
    # The model was never called: cancel fired before the first stream.
    assert call_count == 0
    # The event was cleared after consumption.
    assert not cancel.is_set()


def test_cancel_event_none_preserves_normal_run(monkeypatch, tmp_path):
    """With cancel_event=None the run proceeds normally and emits agent_end."""
    target = tmp_path / "hello.txt"
    target.write_text("hello world")
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(_tool_then_text_turns(str(target))))
    events: list[dict] = []
    monkeypatch.setattr(agent, "emit", events.append)

    asyncio.run(agent.run_agent("read the file"))

    types = [e["type"] for e in events]
    assert "agent_end" in types
    assert "agent_cancelled" not in types


# ── Helpers for widget colour assertions ─────────────────────────────────────


def _status_text(bar: StatusBar) -> Text | str:
    return bar._Static__content


# ── Integration: modal keybindings + theme wiring via Pilot ──────────────────


def test_app_starts_in_normal_mode():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test():
            assert app.mode == "normal"

    asyncio.run(_run())


def test_i_enters_insert_and_focuses_input():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            await pilot.press("i")
            await pilot.pause()
            assert app.mode == "insert"
            assert app.query_one(InputBox).has_focus

    asyncio.run(_run())


def test_escape_returns_to_normal():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            await pilot.press("i")
            await pilot.pause()
            assert app.mode == "insert"
            await pilot.press("escape")
            await pilot.pause()
            assert app.mode == "normal"

    asyncio.run(_run())


def test_check_action_blocks_scroll_in_insert_mode():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test():
            app.mode = "insert"
            assert app.check_action("scroll_down", None) is False
            assert app.check_action("scroll_up", None) is False
            app.mode = "normal"
            assert app.check_action("scroll_down", None) is True

    asyncio.run(_run())


def test_submit_queues_message_and_returns_to_normal():
    pending: list[dict] = []

    async def _run():
        app = AgentApp("noop", pending)
        async with app.run_test() as pilot:
            await pilot.press("i")
            await pilot.pause()
            box = app.query_one(InputBox)
            box.value = "steer here"
            await pilot.press("enter")
            await pilot.pause()
            assert app.mode == "normal"

    asyncio.run(_run())

    assert pending == [{"role": "user", "content": "steer here"}]


def test_ctrl_c_sets_cancel_event():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test():
            assert not app.cancel_event.is_set()
            app.action_cancel_turn()
            assert app.cancel_event.is_set()

    asyncio.run(_run())


def test_default_theme_is_dark():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test():
            assert app.theme_dict["tool_ok"] == "bright_green"
            assert app.query_one(ToolPanel)._theme["tool_ok"] == "bright_green"
            assert app.query_one(StatusBar)._color == "grey70"

    asyncio.run(_run())


def test_light_theme_changes_widget_colors(monkeypatch):
    monkeypatch.setenv("AGENT_THEME", "light")

    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            panel = app.query_one(ToolPanel)
            bar = app.query_one(StatusBar)
            # ToolPanel "tool_ok" color is the light-theme value.
            assert panel._theme["tool_ok"] == THEMES["light"]["tool_ok"]
            # StatusBar "status" color is the light-theme value.
            assert bar._color == THEMES["light"]["status"]
            # And the applied color surfaces on a finished tool row.
            panel.add_tool_row(0, "read_file")
            panel.finish_tool_row(0, ok=True, chars=10)
            await pilot.pause()
            icon = panel.get_cell("0", "icon")
            assert isinstance(icon, Text)
            assert icon.style == THEMES["light"]["tool_ok"]

    asyncio.run(_run())


def test_cancelled_event_routes_to_status_bar(monkeypatch, tmp_path):
    """agent_cancelled routed through handle_agent_event shows 'cancelled'."""

    async def _run():
        app = AgentApp("noop")
        set_app(app)
        async with app.run_test() as pilot:
            app.handle_agent_event({"type": "agent_cancelled"})
            await pilot.pause()
            content = _status_text(app.query_one(StatusBar))
            text = content.plain if isinstance(content, Text) else str(content)
            assert "cancelled" in text

    asyncio.run(_run())
