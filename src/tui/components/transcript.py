# src/tui/components/transcript.py

"""The transcript pane: an append-only scrollable log of assistant output."""

from __future__ import annotations

from rich.markdown import Markdown
from textual.widgets import RichLog


class TranscriptPane(RichLog):
    """Append-only scrollable transcript of assistant output with markdown support.

    Receives text_delta events from the TUI renderer and appends each fragment.
    Auto-scrolls to the bottom as new text arrives; suspends auto-scroll when
    the user manually scrolls up, and resumes when they scroll back to the bottom.

    Markdown rendering: Accumulates text deltas in a buffer and renders as markdown
    on turn completion. During streaming, shows raw text for responsiveness.
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
        self._current_turn_buffer = ""  # Accumulates deltas for the current turn

    def append_text(self, delta: str) -> None:
        """Append a streamed text fragment. Called by the TUI renderer."""
        self._current_turn_buffer += delta
        # Stream raw text for immediate feedback
        self.write(delta, expand=True, scroll_end=True)

    def append_user_text(self, text: str) -> None:
        """Echo a submitted user message, styling it with the theme "user" color."""
        from rich.text import Text

        color = self._theme.get("user", "bright_cyan")
        self.write(Text(text, style=color), expand=True, scroll_end=True)

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
        """Finalize the current turn by re-rendering as markdown if needed.

        When markdown syntax is detected in the buffered text, clears the log
        and re-renders with proper formatting. Otherwise keeps the raw streamed
        text. Resets the buffer for the next turn.
        """
        if not self._current_turn_buffer.strip():
            self._current_turn_buffer = ""
            return

        # Check if markdown syntax is present
        has_markdown = self._contains_markdown(self._current_turn_buffer)

        if has_markdown:
            # Re-render as markdown
            self.clear()
            md = Markdown(
                self._current_turn_buffer,
                code_theme="monokai",
                inline_code_lexer="python",
            )
            self.write(md, expand=True, scroll_end=True)

        # Reset buffer
        self._current_turn_buffer = ""

    def _contains_markdown(self, text: str) -> bool:
        """Check if text contains markdown syntax worth re-rendering."""
        # Headers
        if text.startswith("#") or "\n#" in text:
            return True
        # Code blocks
        if "```" in text:
            return True
        # Bold
        if "**" in text:
            return True
        # Italic/inline code (simple check)
        if ("*" in text and not text.count("*") == 1) or "`" in text:
            return True
        # Lists
        for line in text.split("\n"):
            stripped = line.lstrip()
            if stripped.startswith("- ") or (
                stripped and stripped[0].isdigit() and ". " in stripped[:4]
            ):
                return True
        # Blockquotes
        if text.startswith(">") or "\n>" in text:
            return True
        # Links
        if "](" in text:
            return True
        return False

    def get_text(self) -> str:
        """Get all text content from the transcript for state serialization."""
        return self._current_turn_buffer
