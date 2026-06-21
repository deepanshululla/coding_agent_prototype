# src/tui/components/transcript.py

"""The transcript pane: an append-only scrollable log of assistant output."""

from __future__ import annotations

from rich.markdown import Markdown
from textual.binding import Binding
from textual.widgets import RichLog


class TranscriptPane(RichLog):
    """Append-only scrollable transcript of assistant output with markdown support.

    Receives text_delta events from the TUI renderer and appends each fragment.
    Auto-scrolls to the bottom as new text arrives; suspends auto-scroll when
    the user manually scrolls up, and resumes when they scroll back to the bottom.

    Markdown rendering: Accumulates text deltas in a buffer and renders as markdown
    on turn completion. During streaming, shows raw text for responsiveness.

    Text selection: Users can select text with mouse or keyboard (Shift+arrows),
    and copy selected text with Ctrl+C.
    """

    DEFAULT_CSS = """
    TranscriptPane {
        height: 1fr;
        border: solid $panel;
        padding: 0 1;
    }
    """

    # Enable keyboard focus so user can navigate and select text
    can_focus = True

    BINDINGS = [
        # Priority=True so copy takes precedence over app-level ctrl+c (cancel) when focused
        Binding("ctrl+c", "copy", "Copy", show=False, priority=True),
        Binding("ctrl+a", "select_all", "Select all", show=False),
    ]

    def __init__(self, *args, theme: dict[str, str] | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._theme = theme or {}
        self._current_turn_buffer = ""  # Accumulates deltas for the current turn
        # The in-progress (not yet newline-terminated) line. Streamed deltas are
        # accumulated here and only written once the line is complete, so a
        # logical line lands on ONE RichLog row instead of fragmenting at delta
        # boundaries ("...features R" then "ichLog supports...").
        self._pending_line = ""

    def append_text(self, delta: str) -> None:
        """Append a streamed text fragment, keeping logical lines intact.

        RichLog renders every write() as its own row, so writing each streamed
        delta verbatim fragments a sentence wherever a chunk boundary fell ("R"
        then "ichLog"). Instead we accumulate the open line and write only
        *completed* lines (split on newline); the trailing open line is committed
        at the next flush point (a tool/user echo or turn end). In-place editing
        of a partial row isn't viable — RichLog defers rendering while the pane
        is still unsized at startup, so a live partial can't be reliably removed.
        """
        self._current_turn_buffer += delta
        combined = self._pending_line + delta
        # The last segment is the still-open line; everything before it is final.
        *complete, self._pending_line = combined.split("\n")
        for line in complete:
            self.write(line, expand=True, scroll_end=True)

    def _flush_pending(self) -> None:
        """Commit the open line as a row (before a tool/user echo or turn end)."""
        if self._pending_line:
            self.write(self._pending_line, expand=True, scroll_end=True)
            self._pending_line = ""

    def append_user_text(self, text: str) -> None:
        """Echo a submitted user message, styling it with the theme "user" color."""
        from rich.text import Text

        self._flush_pending()
        color = self._theme.get("user", "bright_cyan")
        self.write(Text(text, style=color), expand=True, scroll_end=True)

    def append_tool_call(self, name: str, tool_input: dict | None) -> None:
        """Render a tool call as a Claude-Code-style summary line in the transcript.

        A ``●`` headline names the action (Reading file, Running command, Edited
        path …) and, when there's a target to show, an indented ``└`` line gives
        the path / command — so the main window says which file was read, which
        command ran, and which file changed. Expandable calls (reads/edits/writes)
        carry a "(ctrl+o to expand)" hint; the toggle itself is a follow-up.
        """
        from rich.text import Text

        from tui.tool_format import format_tool_call

        self._flush_pending()  # finalize any open streamed line above the tool line
        disp = format_tool_call(name, tool_input)
        accent = self._theme.get("tool_name", "yellow")
        muted = self._theme.get("status", "grey70")

        header = Text()
        header.append("● ", style=accent)
        header.append(disp.summary, style=accent)
        # An in-progress verb ("Reading file") trails an ellipsis; a completed,
        # counted summary ("Edited x.py (+5 −3)") does not.
        if not disp.summary.endswith(")"):
            header.append("…", style=muted)
        if disp.expandable:
            header.append("  (ctrl+o to expand)", style=muted)
        self.write(header, expand=True, scroll_end=True)

        if disp.detail:
            self.write(Text(f"  └ {disp.detail}", style=muted), expand=True, scroll_end=True)

    def append_markdown(self, markdown_text: str) -> None:
        """Append markdown-formatted text with proper rendering.

        Uses Rich's Markdown class to parse and render markdown syntax including:
        - Headers (# ## ###)
        - Bold (**text**) and italic (*text*)
        - Code blocks (```lang ... ```)
        - Inline code (`code`)
        - Lists (- item, 1. item)
        - Blockquotes and more
        """
        md = Markdown(markdown_text, code_theme="monokai", inline_code_lexer="python")
        self.write(md, expand=True, scroll_end=True)

    def finalize_turn(self) -> None:
        """Close out the current turn by resetting the streaming buffer.

        Deliberately does NOT clear()+re-render the buffered text as markdown.
        A full clear is the only clear RichLog offers (it's append-only), so it
        would wipe prior turns AND the inline tool-call lines this pane now
        interleaves — losing far more than it gains. Streamed text therefore
        stays as streamed; see plans/2026-06-20-tui-markdown-rendering.md, whose
        "Actual Implementation" reached the same conclusion (no re-render).
        """
        self._flush_pending()  # commit the last open line of the turn
        self._current_turn_buffer = ""

    def get_text(self) -> str:
        """Get all text content from the transcript for state serialization."""
        return self._current_turn_buffer

    def action_copy(self) -> None:
        """Copy selected text to clipboard.

        This action is triggered when the user presses Ctrl+C while the transcript
        has focus and text is selected. It retrieves the selected text and copies
        it to the system clipboard via the app's copy_to_clipboard method.

        If no text is selected, this action does nothing, allowing the app-level
        Ctrl+C (cancel) binding to handle it instead.
        """
        if self.text_selection:
            # Get the selected text via the screen's method
            selected_text = self.screen.get_selected_text()
            if selected_text:
                # Copy to clipboard via the app
                self.app.copy_to_clipboard(selected_text)
                return  # Consume the event
        # If no selection, don't consume the event - let app-level cancel handle it
        # Note: Textual will bubble the event up if we don't explicitly stop it

    def action_select_all(self) -> None:
        """Select all text in the transcript.

        This action is triggered when the user presses Ctrl+A while the transcript
        has focus. It selects all content in the transcript pane.
        """
        self.text_select_all()
