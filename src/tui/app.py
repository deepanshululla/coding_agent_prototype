# src/tui/app.py

"""The Textual app that hosts the agent and renders its events.

AgentApp is the asyncio host: it mounts the TranscriptPane, starts
run_agent as a background Task, and exposes handle_agent_event so the
renderer can push events in.
"""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.containers import Horizontal

from tui.components.tool_panel import ToolPanel
from tui.components.transcript import TranscriptPane


class AgentApp(App):
    """TUI with transcript + tool panel (Layer 10.3)."""

    CSS = """
    Screen {
        layout: vertical;
    }
    Horizontal {
        height: 1fr;
    }
    """

    def __init__(self, task: str) -> None:
        super().__init__()
        # NB: Textual's App reserves both `task` (a read-only property) and the
        # private `_task` attribute (the run Task), so store ours distinctly.
        self._agent_task = task
        # Populated when the agent run completes; mostly useful for tests.
        self.agent_history: list[dict] | None = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield TranscriptPane(highlight=True, markup=False)
            yield ToolPanel()

    async def on_mount(self) -> None:
        # Import here to avoid a circular dependency: agent imports renderer,
        # renderer imports tui.emit, tui.emit is set up before run_agent starts.
        from agent import run_agent

        async def _drive() -> None:
            self.agent_history = await run_agent(self._agent_task)

        asyncio.create_task(_drive())

    def handle_agent_event(self, event: dict) -> None:
        t = event["type"]
        if t == "text_delta":
            self.query_one(TranscriptPane).append_text(event["delta"])
        elif t == "tool_call_start":
            self.query_one(ToolPanel).add_tool_row(event["index"], event["name"])
        elif t == "tool_call_end":
            self.query_one(ToolPanel).finish_tool_row(
                event["index"],
                ok=not event["is_error"],
                chars=event["chars"],
            )
        # turn_end / agent_end: the panel keeps the last turn's results visible
        # until the next turn's first tool_call_start (clear_rows) overwrites
        # them. The status bar in Layer 10.4 consumes turn_end / agent_end.
