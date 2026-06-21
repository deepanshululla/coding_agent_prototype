# src/tui/components/input_box.py

"""The input box: a single-line Input that submits a task on Enter.

Pressing Enter posts an InputBox.Submitted message (Textual's event bus) and
clears the field. The AgentApp handler appends the text to pending_messages so
the outer loop can pick it up — foreshadowing Phase 15 steering.

Tab autocomplete for slash commands:
- When input starts with "/", Tab cycles through matching commands
- Shift+Tab cycles backward through matches
- Editing the input resets the completion state
"""

from __future__ import annotations

from textual.events import Key
from textual.message import Message
from textual.widgets import Input


class InputBox(Input):
    """Single-line input for submitting a task or a steering follow-up.

    Pressing Enter posts InputBox.TextSubmitted. The AgentApp handler appends
    the text to pending_messages so the outer loop can pick it up.

    Tab autocomplete for slash commands:
    - When input starts with "/", Tab cycles through matching commands
    - Shift+Tab cycles backward
    - Editing resets completion state

    NB: the message is named TextSubmitted rather than Submitted on purpose.
    Input already defines (and posts) Input.Submitted internally as
    `self.Submitted(self, value, result)`; shadowing that name on the subclass
    would hijack Textual's own post and crash with an arity mismatch. We listen
    to the base Input.Submitted and re-emit our own distinctly-named message.
    """

    # Layout (height 1, no border) comes from compact=True at construction; this
    # only sets the surface background. A tall focus border would squeeze the
    # single text row out of view, so the box must stay compact.
    DEFAULT_CSS = """
    InputBox {
        background: $surface;
    }
    """

    class TextSubmitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Autocomplete state: candidates and current index in the cycle
        self._completion_candidates: list[str] = []
        self._completion_index: int = -1
        self._completion_prefix: str = ""

    def _reset_completion(self) -> None:
        """Clear autocomplete state."""
        self._completion_candidates = []
        self._completion_index = -1
        self._completion_prefix = ""

    def _get_completions(self, prefix: str) -> list[str]:
        """Return slash commands matching the given prefix.

        For "/" alone, return all commands.
        For "/mo", return commands starting with "mo".
        """
        from tui.commands import get_command_names

        if not prefix.startswith("/"):
            return []

        query = prefix[1:].lower()  # strip the leading "/"
        commands = get_command_names()

        if not query:
            return commands

        return [cmd for cmd in commands if cmd.startswith(query)]

    async def _on_key(self, event: Key) -> None:
        """Handle Tab/Shift+Tab for autocomplete of slash commands."""
        # Only autocomplete if input starts with "/"
        if not self.value.startswith("/"):
            self._reset_completion()
            return await super()._on_key(event)

        if event.key in ("tab", "shift+tab"):
            # Prevent default Tab behavior
            event.prevent_default()

            # If completion state is stale (prefix changed), rebuild candidates
            if self.value != self._completion_prefix:
                self._completion_candidates = self._get_completions(self.value)
                self._completion_index = -1
                self._completion_prefix = self.value

            if not self._completion_candidates:
                return  # no matches, do nothing

            # Cycle forward or backward through candidates
            if event.key == "shift+tab":
                # Shift+Tab: cycle backward
                self._completion_index = (self._completion_index - 1) % len(
                    self._completion_candidates
                )
            else:
                # Tab: cycle forward
                self._completion_index = (self._completion_index + 1) % len(
                    self._completion_candidates
                )

            # Update input with selected completion
            selected = self._completion_candidates[self._completion_index]
            self.value = f"/{selected}"
            self.cursor_position = len(self.value)
            self._completion_prefix = self.value
            return

        # Any other key resets completion state
        self._reset_completion()
        await super()._on_key(event)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Empty / whitespace-only submissions are filtered out before posting.
        if event.value.strip():
            self.post_message(self.TextSubmitted(event.value.strip()))
            self.clear()
            self._reset_completion()
