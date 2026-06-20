# src/tui/app.py

"""The Textual app that hosts the agent and renders its events.

AgentApp is the asyncio host: it mounts the four-region layout, starts
run_agent as a background Task, and exposes handle_agent_event so the
renderer can push events in.

Phase 10.5 adds Vim-style modal keybindings (NORMAL / INSERT / COMMAND), a
cooperative Ctrl-C cancel via an asyncio.Event, and AGENT_THEME-driven
semantic color schemes passed into each widget at construction time.
"""

from __future__ import annotations

import asyncio
import os

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive

from tui.components.input_box import InputBox
from tui.components.status_bar import StatusBar
from tui.components.tool_panel import ToolPanel
from tui.components.transcript import TranscriptPane
from tui.themes import get_theme


class AgentApp(App):
    """Full four-region TUI with Vim-style modal keybindings and themes."""

    mode: reactive[str] = reactive("normal")  # "normal" | "insert" | "command"

    BINDINGS = [
        Binding("j",      "scroll_down",   "Down",    show=False),
        Binding("k",      "scroll_up",     "Up",      show=False),
        Binding("g,g",    "scroll_top",    "Top",     show=False),
        Binding("G",      "scroll_bottom", "Bottom",  show=False),
        Binding("i",      "enter_insert",  "Insert",  show=True),
        Binding("colon",  "enter_command", "Command", show=True),
        Binding("escape", "enter_normal",  "Normal",  show=False),
        Binding("ctrl+c", "cancel_turn",   "Cancel",  show=True),
    ]

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
        # Set on Ctrl-C; run_agent checks it cooperatively at each inner pass.
        self.cancel_event = asyncio.Event()
        # Read once at construction; live theme switching is out of scope.
        self.theme_dict = get_theme(os.getenv("AGENT_THEME", "dark"))

    def check_action(self, action: str, parameters: object) -> bool:
        # Scroll motions only fire in NORMAL; INSERT owns the keyboard for typing
        # so j/k/g/G can be typed freely into the input box.
        if self.mode == "insert" and action in {
            "scroll_down", "scroll_up", "scroll_top", "scroll_bottom"
        }:
            return False
        return True

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield TranscriptPane(highlight=True, markup=False, theme=self.theme_dict)
            yield ToolPanel(theme=self.theme_dict)
        yield InputBox(placeholder="Type a steering message and press Enter…")
        yield StatusBar(theme=self.theme_dict)

    async def on_mount(self) -> None:
        # Start in NORMAL mode with the transcript focused so the App-level
        # j/k/i/colon bindings fire. If the InputBox kept focus (Textual's
        # default first-focusable), it would swallow `i` as typed text and the
        # modal bindings would never trigger.
        self.query_one(TranscriptPane).focus()

        # Import here to avoid a circular dependency: agent imports renderer,
        # renderer imports tui.emit, tui.emit is set up before run_agent starts.
        from agent import run_agent

        async def _drive() -> None:
            # Pass pending_messages and cancel_event into run_agent so the outer
            # loop can receive steering messages and the inner loop can cancel.
            self.agent_history = await run_agent(
                self._agent_task, self._pending, self.cancel_event
            )

        asyncio.create_task(_drive())

    # ── Mode actions ─────────────────────────────────────────────────────────

    def action_enter_insert(self) -> None:
        self.mode = "insert"
        self.query_one(InputBox).focus()

    def action_enter_command(self) -> None:
        self.mode = "command"

    def action_enter_normal(self) -> None:
        self.mode = "normal"
        self.query_one(TranscriptPane).focus()

    # ── Scroll actions (NORMAL mode only, gated by check_action) ─────────────

    def action_scroll_down(self) -> None:
        self.query_one(TranscriptPane).scroll_down()

    def action_scroll_up(self) -> None:
        self.query_one(TranscriptPane).scroll_up()

    def action_scroll_top(self) -> None:
        self.query_one(TranscriptPane).scroll_home()

    def action_scroll_bottom(self) -> None:
        self.query_one(TranscriptPane).scroll_end()

    # ── Cancel action (any mode) ─────────────────────────────────────────────

    def action_cancel_turn(self) -> None:
        """Signal the running inner loop to stop after the current iteration."""
        self.cancel_event.set()
        # The status bar updates when the agent_cancelled event arrives.

    # ── Event handlers ───────────────────────────────────────────────────────

    def on_input_box_text_submitted(self, message: InputBox.TextSubmitted) -> None:
        """Push the submitted text into pending_messages, echo it, and return
        to NORMAL mode."""
        self._pending.append({"role": "user", "content": message.text})
        # Echo the user message in the transcript so they can see it.
        self.query_one(TranscriptPane).append_user_text(f"\n> {message.text}\n")
        self.action_enter_normal()  # return to NORMAL after submitting

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
        elif t == "agent_cancelled":
            self.query_one(StatusBar).set_cancelled()
