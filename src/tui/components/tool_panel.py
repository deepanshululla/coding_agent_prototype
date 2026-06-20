# src/tui/components/tool_panel.py

"""The tool panel: a live status table of tool calls in the current turn.

One row per tool call. Rows are added on tool_call_start (with a spinner) and
updated on tool_call_end (resolving to ✓ with a char count or ✗ on error). The
panel is cleared at the start of each new turn via clear_rows().
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.widgets import DataTable


@dataclass
class _ToolRow:
    index: int
    name: str
    status: str = "pending"  # "pending" | "ok" | "error"
    detail: str = ""


class ToolPanel(DataTable):
    """Live tool-call status table.

    One row per tool call in the current inner-loop turn. Rows are added on
    tool_call_start (with a spinner) and updated on tool_call_end (✓ or ✗).
    """

    DEFAULT_CSS = """
    ToolPanel {
        height: 1fr;
        width: 30;
        border: solid $panel;
    }
    """

    def __init__(self) -> None:
        super().__init__(show_header=False, show_cursor=False)
        self._rows: dict[int, _ToolRow] = {}

    def on_mount(self) -> None:
        self.add_column("icon", width=2, key="icon")
        self.add_column("name", width=18, key="name")
        self.add_column("detail", width=8, key="detail")

    def add_tool_row(self, index: int, name: str) -> None:
        """Called on tool_call_start — adds a spinner row.

        If this index already has a row, we have entered a new turn that reuses
        the same indices: clear the panel first so it shows only the most recent
        turn's activity (the row key str(index) must also be unique for add_row).
        """
        if index in self._rows:
            self.clear_rows()
        row = _ToolRow(index=index, name=name)
        self._rows[index] = row
        self.add_row("⏳", name, "", key=str(index))

    def finish_tool_row(self, index: int, ok: bool, chars: int) -> None:
        """Called on tool_call_end — resolves the spinner to ✓ or ✗."""
        if index not in self._rows:
            return
        row = self._rows[index]
        row.status = "ok" if ok else "error"
        row.detail = f"{chars:,}c" if ok else "err"

        style = "bright_green" if ok else "bright_red"
        icon = Text("✓" if ok else "✗", style=style)
        detail = Text(row.detail, style=style)

        self.update_cell(str(index), "icon", icon)
        self.update_cell(str(index), "detail", detail)

    def clear_rows(self) -> None:
        """Clear the panel at the start of a new turn."""
        self.clear()
        self._rows.clear()
