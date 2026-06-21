# src/tui/components/activity_panel.py

"""The activity panel: a persistent, scrolling log of model and tool calls.

The right pane is a chronological feed of everything the agent does this
session — model turns and tool calls interleaved in the order they happen,
plus a one-shot "thinking" marker per turn. A totals header counts model
calls, tool calls, and elapsed time.

Unlike the old per-turn tool table, the log is NOT cleared between turns:
activity accumulates so the run's history stays visible (and the pane never
sits empty between turns). Rows are keyed by turn so reused tool indices in
later turns get distinct rows.

Event → method mapping (wired in tui/app.py):
  turn_start       → start_turn(iteration, model)   # spinner row for the model call
  turn_end         → end_turn(iteration, reason, n) # resolve to its finish reason
  thinking_delta   → note_thinking()                # one 💭 row per turn
  tool_call_start  → add_tool(index, name)          # spinner row for the tool
  tool_call_end    → finish_tool(index, ok, chars)  # resolve to ✓ / ✗
"""

from __future__ import annotations

import time

from rich.text import Text
from textual.containers import Vertical
from textual.widgets import DataTable, Static


class ActivityPanel(Vertical):
    """Totals header + scrolling activity log of model and tool calls."""

    DEFAULT_CSS = """
    ActivityPanel {
        width: 34;
        border: solid $panel;
    }
    ActivityPanel > #activity-totals {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    ActivityPanel > #activity-log {
        height: 1fr;
    }
    """

    def __init__(self, theme: dict[str, str] | None = None) -> None:
        super().__init__()
        self._theme = theme or {}
        # Monotonic turn counter used for row keys. The agent's per-turn
        # `iteration` resets to 1 on each steering pass, so it can't key rows
        # uniquely across an entire session — this sequence can. The iteration
        # number is still shown in the row label.
        self._turn_seq = 0
        # Row key of the turn currently streaming; tool/thinking rows hang off it
        # so a reused tool index in a later turn still gets a distinct row.
        self._current_key = ""
        # Per-turn guard so repeated thinking_delta events add only one 💭 row.
        self._thinking_seen: set[str] = set()
        self._model_calls = 0
        self._tool_calls = 0
        self._start = time.monotonic()
        # Last rendered totals line, kept as plain text for display and tests.
        self.totals_text = ""

    def compose(self):
        yield Static(id="activity-totals")
        table = DataTable(id="activity-log", show_header=False, show_cursor=False)
        yield table

    def on_mount(self) -> None:
        self.log.add_column("icon", width=2, key="icon")
        self.log.add_column("label", width=18, key="label")
        self.log.add_column("detail", width=8, key="detail")
        self._refresh_totals()
        # Keep elapsed time ticking even when no events arrive.
        self.set_interval(1.0, self._refresh_totals)

    # ── Child-widget accessors ───────────────────────────────────────────────

    @property
    def log(self) -> DataTable:
        return self.query_one("#activity-log", DataTable)

    @property
    def totals(self) -> Static:
        return self.query_one("#activity-totals", Static)

    # ── Session counters (read by the /usage command) ────────────────────────

    @property
    def model_calls(self) -> int:
        return self._model_calls

    @property
    def tool_calls(self) -> int:
        return self._tool_calls

    def elapsed_seconds(self) -> int:
        return int(time.monotonic() - self._start)

    # ── Model-call (turn) rows ───────────────────────────────────────────────

    def start_turn(self, iteration: int, model: str) -> None:
        """A model call began (turn_start): add a spinner row naming the model."""
        self._turn_seq += 1
        self._current_key = f"t{self._turn_seq}"
        self._model_calls += 1
        label = f"{_short_model(model)} · t{iteration}"
        self.log.add_row("⏳", label, "", key=self._current_key)
        self._after_append()

    def end_turn(self, iteration: int, finish_reason: str, tool_calls_count: int) -> None:
        """A model call finished (turn_end): resolve its row to the finish reason.

        turn_end always follows its own turn_start with no intervening turn, so
        the most recently started turn (``_current_key``) is the one to resolve.
        """
        if not self._has_row(self._current_key):
            return
        color = self._theme.get("status", "grey70")
        self.log.update_cell(self._current_key, "icon", Text("●", style=color))
        self.log.update_cell(
            self._current_key, "detail", Text(_short_reason(finish_reason), style=color)
        )

    def note_thinking(self) -> None:
        """The model is reasoning (thinking_delta): add one 💭 row for this turn."""
        if self._current_key in self._thinking_seen:
            return
        self._thinking_seen.add(self._current_key)
        self.log.add_row("💭", "thinking…", "", key=f"{self._current_key}-think")
        self._after_append()

    # ── Tool-call rows ───────────────────────────────────────────────────────

    def add_tool(self, index: int, name: str, tool_input: dict | None = None) -> None:
        """A tool call began (tool_call_start): add a spinner row under this turn.

        When the call's input is known, the row names its target too (``Read
        agent.py``, ``Bash git push``) so the panel says *which* file/command,
        not just the tool type. The detail is kept short for the narrow column.
        """
        self._tool_calls += 1
        label = name
        if tool_input:
            from tui.tool_format import format_tool_call

            short = format_tool_call(name, tool_input).short
            if short:
                label = f"{name} {short}"
        self.log.add_row("⏳", label, "", key=self._tool_key(index))
        self._after_append()

    def finish_tool(self, index: int, ok: bool, chars: int) -> None:
        """A tool call finished (tool_call_end): resolve its row to ✓ / ✗."""
        key = self._tool_key(index)
        if not self._has_row(key):
            return
        role = "tool_ok" if ok else "tool_error"
        style = self._theme.get(role, "bright_green" if ok else "bright_red")
        self.log.update_cell(key, "icon", Text("✓" if ok else "✗", style=style))
        detail = f"{chars:,}c" if ok else "err"
        self.log.update_cell(key, "detail", Text(detail, style=style))

    # ── Internals ────────────────────────────────────────────────────────────

    def _tool_key(self, index: int) -> str:
        return f"{self._current_key}-tool{index}"

    def _has_row(self, key: str) -> bool:
        try:
            self.log.get_row(key)
            return True
        except Exception:
            return False

    def _after_append(self) -> None:
        # Keep the newest activity in view and the counters current.
        self.log.scroll_end(animate=False)
        self._refresh_totals()

    def _refresh_totals(self) -> None:
        elapsed = int(time.monotonic() - self._start)
        color = self._theme.get("status", "grey70")
        line = f" ▶ {self._model_calls} model · {self._tool_calls} tools · {elapsed}s"
        self.totals_text = line
        self.totals.update(Text(line, style=color))


def _short_reason(finish_reason: str) -> str:
    """Compact label for a finish reason to fit the narrow detail column."""
    return {"tool_calls": "tools", "length": "len"}.get(finish_reason, finish_reason)


def _short_model(model: str) -> str:
    """Compact a model id for the narrow label column.

    Drops any provider prefix ("anthropic/claude-…" → "claude-…") and the
    "claude-" family prefix so the readable variant is what shows, e.g.
    "anthropic/claude-sonnet-4-5" → "sonnet-4-5". Falls back to "model" for an
    empty id so the row is never blank.
    """
    name = (model or "").rsplit("/", 1)[-1]
    if name.startswith("claude-"):
        name = name[len("claude-") :]
    return name or "model"
