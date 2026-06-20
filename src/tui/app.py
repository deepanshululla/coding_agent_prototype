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

from tui.components.input_box import InputBox
from tui.components.status_bar import StatusBar
from tui.components.tool_panel import ToolPanel
from tui.components.transcript import TranscriptPane


class AgentApp(App):
    """Full four-region TUI: transcript | tool panel / input box / status bar."""

    CSS = """
    Screen {
        layout: vertical;
    }
    Horizontal {
        height: 1fr;
    }
    """

    def __init__(self, task: str, pending_messages: list[dict] | None = None) -> None:
        super().__init__()
        # NB: Textual's App reserves both `task` (a read-only property) and the
        # private `_task` attribute (the run Task), so store ours distinctly.
        self._agent_task = task
        # Shared reference; the input box appends here and run_agent reads it.
        self._pending: list[dict] = pending_messages if pending_messages is not None else []
        # Populated when the agent run completes; mostly useful for tests.
        self.agent_history: list[dict] | None = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield TranscriptPane(highlight=True, markup=False)
            yield ToolPanel()
        yield InputBox(placeholder="Type a task and press Enter…")
        yield StatusBar()

    async def on_mount(self) -> None:
        # Import here to avoid a circular dependency: agent imports renderer,
        # renderer imports tui.emit, tui.emit is set up before run_agent starts.
        from agent import run_agent

        async def _drive() -> None:
            # Pass pending_messages into run_agent so the outer loop can receive
            # steering messages from the input box.
            self.agent_history = await run_agent(self._agent_task, self._pending)

        asyncio.create_task(_drive())

    def on_input_box_text_submitted(self, message: InputBox.TextSubmitted) -> None:
        """Push the submitted text into pending_messages and echo it."""
        self._pending.append({"role": "user", "content": message.text})
        # Echo the user message in the transcript so they can see it.
        self.query_one(TranscriptPane).append_text(f"\n> {message.text}\n")

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
        elif t == "turn_end":
            self.query_one(StatusBar).set_iteration(event["iteration"])
        elif t == "agent_end":
            self.query_one(StatusBar).set_done(event["total_iterations"])
