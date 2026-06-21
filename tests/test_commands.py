"""Tests for the TUI slash-command framework (tui/commands.py).

Slash commands are *macros* typed into the input box: text starting with "/"
is intercepted and run locally instead of being sent to the agent as a steering
message. dispatch() returns the text to echo in the transcript, or None when the
text is not a command (so the caller steers as usual).

Unit tests drive dispatch() directly against a live AgentApp (commands read app
state — the status bar, the activity panel, the session usage). The integration
test drives the input box through AgentApp to prove a "/" submission runs a
command and does NOT enqueue a steering message.
"""

import asyncio

import provider
from tui.app import AgentApp
from tui.commands import dispatch
from tui.components.activity_panel import ActivityPanel
from tui.components.input_box import InputBox
from tui.components.status_bar import StatusBar


def test_non_command_returns_none():
    """Plain text is not a command — dispatch returns None so the caller steers."""

    async def _run():
        app = AgentApp("noop")
        async with app.run_test():
            assert dispatch(app, "hello there") is None

    asyncio.run(_run())


def test_unknown_command_reports_error():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test():
            out = dispatch(app, "/nope")
            assert out is not None
            assert "unknown command" in out.lower()
            assert "/help" in out

    asyncio.run(_run())


def test_help_lists_commands():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test():
            out = dispatch(app, "/help")
            assert out is not None
            for name in ("/help", "/model", "/usage"):
                assert name in out

    asyncio.run(_run())


def test_model_no_args_shows_current_model(monkeypatch):
    # monkeypatch pins provider.MODEL and restores it at teardown — even though
    # dispatch may rebind it — so this test never leaks global state.
    monkeypatch.setattr(provider, "MODEL", "claude-sonnet-4-5")

    async def _run():
        app = AgentApp("noop")
        async with app.run_test():
            out = dispatch(app, "/model")
            assert out is not None
            assert "claude-sonnet-4-5" in out

    asyncio.run(_run())


def test_model_with_arg_switches_model(monkeypatch):
    """/model <name> sets the live model and reflects it on the status bar."""
    monkeypatch.setattr(provider, "MODEL", "claude-sonnet-4-5")

    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            out = dispatch(app, "/model gpt-4o")
            assert out is not None
            await pilot.pause()
            # The live model used by subsequent turns is updated.
            assert provider.MODEL == "gpt-4o"
            # The old → new transition is reported.
            assert "claude-sonnet-4-5" in out
            assert "gpt-4o" in out
            # And the status bar shows the new model.
            assert app.query_one(StatusBar)._model == "gpt-4o"

    asyncio.run(_run())


def test_usage_reports_session_counters():
    """/usage reports model calls, tool calls, and elapsed from the panel."""

    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            panel = app.query_one(ActivityPanel)
            panel.start_turn(1, "m")
            panel.add_tool(0, "a")
            panel.add_tool(1, "b")
            await pilot.pause()
            out = dispatch(app, "/usage")
            assert out is not None
            assert "1 model" in out
            assert "2 tool" in out

    asyncio.run(_run())


def test_usage_reports_tokens_when_available():
    """When token usage has been accumulated, /usage includes the totals."""

    async def _run():
        app = AgentApp("noop")
        async with app.run_test():
            app.session_usage = {
                "prompt_tokens": 1200,
                "completion_tokens": 340,
                "total_tokens": 1540,
            }
            out = dispatch(app, "/usage")
            assert out is not None
            assert "1,540" in out or "1540" in out
            assert "1,200" in out or "1200" in out
            assert "340" in out

    asyncio.run(_run())


def test_usage_tokens_na_when_absent():
    """With no token data (e.g. CLI fork didn't report any), /usage says n/a."""

    async def _run():
        app = AgentApp("noop")
        async with app.run_test():
            app.session_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            out = dispatch(app, "/usage")
            assert out is not None
            assert "n/a" in out.lower()

    asyncio.run(_run())


# ── Integration: a "/" submission runs a command, does not steer ─────────────


def test_slash_submission_runs_command_not_steering(monkeypatch):
    """Submitting a "/" line runs the command (observable side effect) and does
    NOT enqueue a steering message for the agent."""
    monkeypatch.setattr(provider, "MODEL", "claude-sonnet-4-5")

    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            box = app.query_one(InputBox)
            box.focus()
            box.value = "/model gpt-4o"
            await pilot.press("enter")
            await pilot.pause()
            # The command ran (model switched) …
            assert provider.MODEL == "gpt-4o"
            # … and nothing was queued as a steering message.
            assert app._steering.empty()

    asyncio.run(_run())
