# src/tui/components/transcript.py

"""The transcript pane: an append-only scrollable log of assistant output."""

from __future__ import annotations

from textual.widgets import RichLog


class TranscriptPane(RichLog):
    """Append-only scrollable transcript of assistant output.

    Receives text_delta events from the TUI renderer and appends each
    fragment. Auto-scrolls to the bottom as new text arrives; suspends
    auto-scroll when the user manually scrolls up, and resumes when they
    scroll back to the bottom.

    The theme dict (Phase 10.5) supplies the "user" color used when echoing a
    user message via append_user_text; assistant text stays unstyled for
    readability.
    """

    DEFAULT_CSS = """
    TranscriptPane {
        height: 1fr;
        border: solid $panel;
        padding: 0 1;
    }
    """

    def __init__(self, *args, theme: dict[str, str] | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._theme = theme or {}

    def append_text(self, delta: str) -> None:
        """Append a streamed text fragment. Called by the TUI renderer."""
        self.write(delta, expand=True, scroll_end=True)

    def append_user_text(self, text: str) -> None:
        """Echo a submitted user message, styling it with the theme "user" color."""
        from rich.text import Text

        color = self._theme.get("user", "bright_cyan")
        self.write(Text(text, style=color), expand=True, scroll_end=True)
