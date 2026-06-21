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

import config
import provider
from tui.components.activity_panel import ActivityPanel
from tui.components.input_box import InputBox
from tui.components.status_bar import StatusBar
from tui.components.transcript import TranscriptPane
from tui.themes import get_theme

# Permission modes cycled by shift+tab, in order. Each pair is the value passed
# to `claude -p --permission-mode` and the short label shown in the status bar.
# Cycling pushes the value to provider.CLI_PERMISSION_MODE, which the CLI fork
# reads per turn — so a switch takes effect on the next message.
_PERMISSION_MODES = [
    ("bypassPermissions", "auto"),
    ("acceptEdits", "edit"),
    ("plan", "plan"),
]


class AgentApp(App):
    """Full four-region TUI with Vim-style modal keybindings and themes."""

    mode: reactive[str] = reactive("normal")  # "normal" | "insert" | "command"
    permission_mode: reactive[str] = reactive("bypassPermissions")

    BINDINGS = [
        Binding("j", "scroll_down", "Down", show=False),
        Binding("k", "scroll_up", "Up", show=False),
        Binding("g,g", "scroll_top", "Top", show=False),
        Binding("G", "scroll_bottom", "Bottom", show=False),
        Binding("i", "enter_insert", "Insert", show=True),
        Binding("colon", "enter_command", "Command", show=True),
        Binding("escape", "enter_normal", "Normal", show=False),
        Binding("ctrl+c", "cancel_turn", "Cancel", show=True),
        # Quit via ctrl+q (any mode) or by typing an exit word. Plain `q` is
        # deliberately NOT bound — it is too easy to hit by accident.
        Binding("ctrl+q", "force_quit", "Quit", show=True),
        # shift+tab cycles the permission mode (auto / edit / plan). priority so
        # it works even while the input box has focus.
        Binding("shift+tab", "cycle_permission", "Perm mode", show=True, priority=True),
        # ctrl+v reads an image off the OS clipboard and attaches it to the next
        # steering message. priority so it fires even while the input box has
        # focus; gated off via check_action when AGENT_IMAGE_PASTE is disabled.
        Binding("ctrl+v", "paste_image", "Paste image", show=True, priority=True),
    ]

    # Words that, when submitted in the input box, quit instead of steering.
    _QUIT_WORDS = {"exit", "quit", ":q", ":quit", ":wq"}

    CSS = """
    Screen {
        layout: vertical;
    }
    Horizontal {
        height: 1fr;
    }
    """

    # Sentinel pushed onto the steering queue to end the run gracefully.
    _SHUTDOWN = object()

    def __init__(
        self,
        task: str,
        pending_messages: list[dict] | None = None,
        hot_reload: bool = False,
        model: str | None = None,
    ) -> None:
        super().__init__()
        # NB: Textual's App reserves both `task` (a read-only property) and the
        # private `_task` attribute (the run Task), so store ours distinctly.
        self._agent_task = task
        self._model = model
        # Legacy echo list (Phase 10.4): the input box still records submissions
        # here for callers that read it, but the steering *channel* is the queue
        # below — that is what actually continues the run.
        self._pending: list[dict] = pending_messages if pending_messages is not None else []
        # Steering channel (the real one): on_input_box_text_submitted puts each
        # follow-up here; _get_steering (wired into run_agent) drains it so the
        # outer loop continues instead of exiting after the first task.
        self._steering: asyncio.Queue = asyncio.Queue()
        # Populated when the agent run completes; mostly useful for tests.
        self.agent_history: list[dict] | None = None
        # Set on Ctrl-C; run_agent checks it cooperatively at each inner pass.
        self.cancel_event = asyncio.Event()
        # Flips True when a quit is requested (key binding or an exit word).
        self._quitting = False
        # Seed the permission mode from the configured CLI default, falling back
        # to the first cycle entry if it is not one we cycle through.
        known = [value for value, _ in _PERMISSION_MODES]
        self.permission_mode = (
            provider.CLI_PERMISSION_MODE
            if provider.CLI_PERMISSION_MODE in known
            else _PERMISSION_MODES[0][0]
        )
        # Read once at construction; live theme switching is out of scope.
        self.theme_dict = get_theme(os.getenv("AGENT_THEME", "dark"))
        # Hot reload mode: when enabled, file watcher restarts the app on changes.
        self._hot_reload = hot_reload
        # Set by trigger_reload so run() can re-exec the process AFTER Textual has
        # torn down and restored the terminal (execing mid-run corrupts it).
        self._reload_requested = False
        # Image content blocks pasted via Ctrl+V, awaiting the next submit. Each
        # is an OpenAI-style {"type": "image_url", ...} block folded into the
        # user message on Enter; cleared once that message is sent.
        self._pending_images: list[dict] = []
        # Running token totals across the session, accumulated from each turn's
        # reported usage (turn_end). Surfaced by the /usage command; stays zero
        # when the provider reports no usage (e.g. the text-only CLI fork).
        self.session_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def check_action(self, action: str, parameters: object) -> bool:
        # Scroll motions only fire in NORMAL; INSERT owns the keyboard for typing
        # so j/k/g/G can be typed freely into the input box.
        if self.mode == "insert" and action in {
            "scroll_down",
            "scroll_up",
            "scroll_top",
            "scroll_bottom",
        }:
            return False
        # Ctrl+V image paste is gated off when AGENT_IMAGE_PASTE is disabled.
        if action == "paste_image" and not config.IMAGE_PASTE:
            return False
        return True

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield TranscriptPane(highlight=True, markup=False, theme=self.theme_dict)
            yield ActivityPanel(theme=self.theme_dict)
        # compact=True keeps the input borderless even on focus — a tall focus
        # border on this height-1 box would squeeze its single text row out of
        # view. select_on_focus=False stops focus from highlighting (and thereby
        # hiding) existing text. Together they fix "text disappears on highlight".
        yield InputBox(
            placeholder="Type a steering message and press Enter…",
            compact=True,
            select_on_focus=False,
        )
        yield StatusBar(theme=self.theme_dict)

    async def on_mount(self) -> None:
        # Start in NORMAL mode with the transcript focused so the App-level
        # j/k/i/colon bindings fire. If the InputBox kept focus (Textual's
        # default first-focusable), it would swallow `i` as typed text and the
        # modal bindings would never trigger.
        self.query_one(TranscriptPane).focus()

        # Show the active permission mode from the start.
        self.query_one(StatusBar).set_permission_mode(self._permission_label())

        # Hot reload: restore state from previous run if available
        if self._hot_reload:
            from datetime import datetime

            from tui.hot_reload import load_tui_state

            state = load_tui_state()
            if state:
                # Restore transcript
                transcript = self.query_one(TranscriptPane)
                if state.get("transcript"):
                    transcript.append_text(state["transcript"])
                # Log reload completion
                timestamp = datetime.now().strftime("%H:%M:%S")
                transcript.append_text(f"\n[hot-reload] Reloaded at {timestamp}\n")

        # Only drive the agent when this app is the live, registered emit target.
        # An AgentApp constructed merely to exercise a child widget (no set_app)
        # is inert — its agent output would route nowhere anyway, and a background
        # run would otherwise race on the shared widgets it mutates.
        from tui.emit import get_app

        if get_app() is not self:
            return

        # Import here to avoid a circular dependency: agent imports renderer,
        # renderer imports tui.emit, tui.emit is set up before run_agent starts.
        from agent import run_agent

        async def _drive() -> None:
            # cancel_event lets the inner loop stop on Ctrl-C; get_steering_messages
            # lets the outer loop continue with follow-ups typed into the input box
            # instead of exiting after the first task. Any crash (e.g. a missing
            # API key) is surfaced via an agent_error event rather than vanishing
            # into a fire-and-forget task.
            try:
                self.agent_history = await run_agent(
                    self._agent_task,
                    cancel_event=self.cancel_event,
                    get_steering_messages=self._get_steering,
                    model=self._model,
                )
            except asyncio.CancelledError:
                raise  # app is shutting down — let the task unwind cleanly
            except Exception as exc:
                self.handle_agent_event(
                    {"type": "agent_error", "message": f"{type(exc).__name__}: {exc}"}
                )

        asyncio.create_task(_drive())

        # Hot reload: start file watcher if enabled
        if self._hot_reload:
            from tui.hot_reload import watch_tui_files

            asyncio.create_task(watch_tui_files(self))

    async def _get_steering(self) -> list[dict]:
        """Block until the user submits a follow-up, then return it to run_agent.

        Wired into run_agent as get_steering_messages: after the inner tool-call
        cycle finishes, the outer loop awaits this. While it blocks the status bar
        shows "waiting"; a submitted message resolves it and the run continues.
        Receiving the _SHUTDOWN sentinel returns [] so the outer loop ends and
        run_agent records its final history.
        """
        self.query_one(StatusBar).set_waiting()
        item = await self._steering.get()
        if item is self._SHUTDOWN:
            return []
        messages = [item]
        # Coalesce anything already queued so a burst of submissions is handled in
        # one pass; a sentinel in the burst is re-queued to end the next poll.
        while not self._steering.empty():
            nxt = self._steering.get_nowait()
            if nxt is self._SHUTDOWN:
                self._steering.put_nowait(self._SHUTDOWN)
                break
            messages.append(nxt)
        return messages

    def request_shutdown(self) -> None:
        """Ask the steering loop to end the run gracefully after the current turn."""
        self._steering.put_nowait(self._SHUTDOWN)

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

    def action_force_quit(self) -> None:
        """Quit from any mode (ctrl+q), even while typing in the input box."""
        self._do_quit()

    def action_cycle_permission(self) -> None:
        """Advance the permission mode (shift+tab): auto → edit → plan → auto.

        The chosen value is pushed to provider.CLI_PERMISSION_MODE so the next
        `claude -p` turn runs under it, and the status bar reflects the change.
        """
        values = [value for value, _ in _PERMISSION_MODES]
        idx = values.index(self.permission_mode) if self.permission_mode in values else 0
        value, label = _PERMISSION_MODES[(idx + 1) % len(_PERMISSION_MODES)]
        self.permission_mode = value
        provider.CLI_PERMISSION_MODE = value
        self.query_one(StatusBar).set_permission_mode(label)

    def _permission_label(self) -> str:
        """Short status-bar label for the current permission mode."""
        for value, label in _PERMISSION_MODES:
            if value == self.permission_mode:
                return label
        return self.permission_mode

    # ── Image paste action (ctrl+v) ───────────────────────────────────────────

    def action_paste_image(self) -> None:
        """Read an image off the OS clipboard and buffer it for the next submit.

        The terminal does not transmit the image on Ctrl+V — this pulls it from
        the clipboard (tui.clipboard) and stores an image_url content block. The
        block is folded into the user message when the user presses Enter. A
        missing image or an oversized one is reported on the status bar and never
        buffered.
        """
        from tui.clipboard import read_clipboard_image, to_data_url

        result = read_clipboard_image()
        if result is None:
            self.query_one(StatusBar).set_hint("no image in clipboard")
            return
        data, mime = result
        if len(data) > config.IMAGE_MAX_BYTES:
            self.query_one(StatusBar).set_hint(
                f"image too large ({len(data)} > {config.IMAGE_MAX_BYTES} bytes)"
            )
            return
        self._pending_images.append(
            {"type": "image_url", "image_url": {"url": to_data_url(data, mime)}}
        )
        n = len(self._pending_images)
        self.query_one(TranscriptPane).append_user_text(f"\n[image {n} attached]\n")
        self.query_one(StatusBar).set_hint(f"image {n} attached — add a message and press Enter")

    def trigger_reload(self) -> None:
        """Request a hot reload: save state, then exit the app cleanly.

        Crucially this does NOT re-exec here. Calling os.execv while Textual still
        owns the terminal (alternate screen + raw mode) skips Textual's teardown
        and leaves the terminal corrupted. Instead we flag the reload and exit;
        run() performs the re-exec once app.run() has returned and the terminal
        has been restored.
        """
        from tui.hot_reload import save_tui_state

        # Save state for restoration after restart, then exit so the terminal is
        # restored before run() re-execs the process.
        save_tui_state(self)
        self._reload_requested = True
        self.exit()

    def _do_quit(self) -> None:
        """Tear down gracefully: end the steering loop, then exit the app."""
        self._quitting = True
        self.request_shutdown()  # let a blocked steering poll return cleanly
        self.exit()

    # ── Event handlers ───────────────────────────────────────────────────────

    def on_input_box_text_submitted(self, message: InputBox.TextSubmitted) -> None:
        """Queue the submitted text for steering, echo it, and return to NORMAL.

        The message goes onto the steering queue (which _get_steering drains to
        continue the run) and is also recorded on the legacy _pending list.
        A bare exit word (exit / quit / :q) quits instead of steering.
        """
        if message.text.strip().lower() in self._QUIT_WORDS:
            self._do_quit()
            return
        # Slash commands are macros run locally, not sent to the agent. A "/"-led
        # line is dispatched and its output echoed in the transcript; the agent's
        # context never sees it and no steering message is queued.
        if message.text.startswith("/"):
            from tui.commands import dispatch

            output = dispatch(self, message.text)
            if output is not None:
                pane = self.query_one(TranscriptPane)
                pane.append_user_text(f"\n{message.text}\n")
                pane.append_text(f"{output}\n")
                self.action_enter_normal()
                return
        # When images are buffered (Ctrl+V), send multimodal list content — text
        # block first, then each image block — and clear the buffer. With none,
        # content stays a plain string so the non-image path is unchanged.
        if self._pending_images:
            content: object = [{"type": "text", "text": message.text}, *self._pending_images]
            self._pending_images = []
        else:
            content = message.text
        msg = {"role": "user", "content": content}
        self._steering.put_nowait(msg)
        self._pending.append(msg)
        # Echo the user message in the transcript so they can see it.
        self.query_one(TranscriptPane).append_user_text(f"\n> {message.text}\n")
        self.action_enter_normal()  # return to NORMAL after submitting

    def handle_agent_event(self, event: dict) -> None:
        t = event["type"]
        if t == "text_delta":
            self.query_one(TranscriptPane).append_text(event["delta"])
        elif t == "turn_start":
            self.query_one(ActivityPanel).start_turn(event["iteration"], event["model"])
        elif t == "thinking_delta":
            self.query_one(ActivityPanel).note_thinking()
        elif t == "tool_call_start":
            tool_input = event.get("input") or {}
            self.query_one(ActivityPanel).add_tool(event["index"], event["name"], tool_input)
            # Echo the call in the main window, naming the file / command / change.
            self.query_one(TranscriptPane).append_tool_call(event["name"], tool_input)
        elif t == "tool_call_end":
            self.query_one(ActivityPanel).finish_tool(
                event["index"],
                ok=not event["is_error"],
                chars=event["chars"],
            )
        elif t == "turn_end":
            # Finalize the turn by re-rendering streamed text as markdown
            self.query_one(TranscriptPane).finalize_turn()
            self.query_one(ActivityPanel).end_turn(
                event["iteration"], event["finish_reason"], event["tool_calls_count"]
            )
            # Accumulate token usage for the /usage command (None when the
            # provider reported none, e.g. the text-only CLI fork).
            usage = event.get("usage")
            if usage:
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    self.session_usage[key] += usage.get(key, 0)
            self.query_one(StatusBar).set_iteration(event["iteration"])
        elif t == "agent_end":
            self.query_one(StatusBar).set_done(event["total_iterations"])
        elif t == "agent_cancelled":
            self.query_one(StatusBar).set_cancelled()
        elif t == "agent_error":
            # Surface a crashed run instead of letting it vanish: show it in the
            # transcript (the visible log) and flag the status bar.
            self.query_one(TranscriptPane).append_text(f"\n[error] {event['message']}\n")
            self.query_one(StatusBar).set_error(event["message"])
