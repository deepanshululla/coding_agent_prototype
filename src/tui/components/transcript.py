# src/tui/components/transcript.py

"""The transcript pane: an append-only scrollable log of assistant output."""

from textual.widgets import RichLog


class TranscriptPane(RichLog):
    """Append-only scrollable transcript of assistant output.

    Receives text_delta events from the TUI renderer and appends each
    fragment. Auto-scrolls to the bottom as new text arrives; suspends
    auto-scroll when the user manually scrolls up, and resumes when they
    scroll back to the bottom.
    """

    DEFAULT_CSS = """
    TranscriptPane {
        height: 1fr;
        border: solid $panel;
        padding: 0 1;
    }
    """

    def append_text(self, delta: str) -> None:
        """Append a streamed text fragment. Called by the TUI renderer."""
        self.write(delta, expand=True, scroll_end=True)
