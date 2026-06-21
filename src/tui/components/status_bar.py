# src/tui/components/status_bar.py

"""The status bar: a single ambient line showing model, iteration, elapsed time.

Updated by turn_end (advance the iteration counter) and agent_end (show 'done').
Reads the model name from the AGENT_MODEL env var for display only — no model
selection logic lives here.
"""

from __future__ import annotations

import os
import time

from textual.widgets import Static


class StatusBar(Static):
    """Ambient status: model name, iteration N/MAX, elapsed time.

    Updated by turn_end (advance counter) and agent_end (show 'done').
    """

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $panel;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def __init__(self, max_iterations: int = 30, theme: dict[str, str] | None = None) -> None:
        super().__init__()
        self._model = os.getenv("AGENT_MODEL", "claude-sonnet-4-5")
        self._max = max_iterations
        self._iter = 0
        self._start = time.monotonic()
        self._done = False
        self._cancelled = False
        self._waiting = False
        self._error: str | None = None
        self._permission: str | None = None
        # Transient one-shot note (e.g. "image 1 attached"); cleared on next turn.
        self._hint: str | None = None
        self._color = (theme or {}).get("status", "grey70")

    def set_iteration(self, n: int) -> None:
        self._iter = n
        # A new turn means the agent is active again, not idle.
        self._waiting = False
        self._hint = None
        self._refresh_label()

    def set_done(self, total: int) -> None:
        self._iter = total
        self._done = True
        self._waiting = False
        self._refresh_label()

    def set_cancelled(self) -> None:
        self._cancelled = True
        self._refresh_label()

    def set_waiting(self) -> None:
        """Show that the agent finished a turn and is idle awaiting input."""
        self._waiting = True
        self._refresh_label()

    def set_error(self, message: str) -> None:
        """Flag that the run failed; the message is rendered (clipped) here."""
        self._error = message
        self._refresh_label()

    def set_model(self, name: str) -> None:
        """Show a new active model (e.g. after the /model command switches it)."""
        self._model = name
        self._refresh_label()

    def set_permission_mode(self, label: str) -> None:
        """Show the active permission mode (e.g. 'auto', 'edit', 'plan')."""
        self._permission = label
        self._refresh_label()

    def set_hint(self, message: str) -> None:
        """Show a transient note (image attached / no image / too large).

        Persists until the next turn event clears it, so a Ctrl+V result stays
        visible while the user keeps typing.
        """
        self._hint = message
        self._refresh_label()

    def _refresh_label(self) -> None:
        # NB: named _refresh_label, NOT _render — Textual's Widget._render() is a
        # reserved internal that must return a Visual; overriding it with a
        # None-returning method crashes the compositor.
        from rich.text import Text

        elapsed = int(time.monotonic() - self._start)
        if self._error is not None:
            clipped = self._error if len(self._error) <= 60 else self._error[:57] + "..."
            state = f"error: {clipped}"
        elif self._cancelled:
            state = "cancelled"
        elif self._waiting:
            state = "waiting for input"
        elif self._done:
            state = f"done ({self._iter} iters)"
        else:
            state = f"iter {self._iter}/{self._max}"
        perm = f"  •  {self._permission}" if self._permission else ""
        line = f" {self._model}{perm}  •  {state}  •  {elapsed}s"
        if self._hint:
            line += f"  •  {self._hint}"
        self.update(Text(line, style=self._color))
