# src/tui/components/input_box.py

"""The input box: a single-line Input that submits a task on Enter.

Pressing Enter posts an InputBox.Submitted message (Textual's event bus) and
clears the field. The AgentApp handler appends the text to pending_messages so
the outer loop can pick it up — foreshadowing Phase 15 steering.
"""

from __future__ import annotations

from textual.message import Message
from textual.widgets import Input


class InputBox(Input):
    """Single-line input for submitting a task or a steering follow-up.

    Pressing Enter posts InputBox.TextSubmitted. The AgentApp handler appends
    the text to pending_messages so the outer loop can pick it up.

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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Empty / whitespace-only submissions are filtered out before posting.
        if event.value.strip():
            self.post_message(self.TextSubmitted(event.value.strip()))
            self.clear()
