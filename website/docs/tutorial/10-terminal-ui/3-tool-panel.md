---
sidebar_position: 3
title: "Layer 10.3 — The Tool Panel"
description: Add a tool panel widget that shows each tool call as a spinner row while running and resolves to ✓ or ✗ when the result arrives.
---

# Layer 10.3 — The Tool Panel

:::note Starting point
The transcript app from Layer 10.2: a single `TranscriptPane` that renders `text_delta` events. `AGENT_UI=tui` launches a full-screen Textual app. The stdout path is unchanged.
:::

When the agent runs tools you currently see nothing in the TUI — the tool activity was only wired to `text_delta` events. This layer adds a **second region** to the right of the transcript: a tool panel that shows each tool call as a live row. The row starts with a spinner when `tool_call_start` arrives and resolves to ✓ (green, with char count) or ✗ (red, with "error") when `tool_call_end` arrives.

Both widgets consume the same events from the same `emit()` seam. No changes to `agent.py`.

## What you'll learn

- How to compose a two-region layout in Textual (horizontal split).
- How to build a `ToolPanel` backed by a `DataTable` with in-place row updates.
- How `tool_call_start` and `tool_call_end` events map to table mutations.
- When to clear the tool panel (between turns, not between iterations).

## Build it

### Step 1 — The `ToolPanel` widget (`src/tui/components/tool_panel.py`)

The panel uses a `DataTable` with three columns: a status icon, a tool name, and a detail field. `add_row` is called on `tool_call_start`; `finish_row` replaces the spinner on `tool_call_end`.

```python
# src/tui/components/tool_panel.py

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from textual.widgets import DataTable
from rich.text import Text


@dataclass
class _ToolRow:
    index: int
    name: str
    status: str = "pending"   # "pending" | "ok" | "error"
    detail: str = ""


class ToolPanel(DataTable):
    """Live tool-call status table.

    One row per tool call in the current inner-loop turn. Rows are added on
    tool_call_start (with a spinner) and updated on tool_call_end (✓ or ✗).
    The panel is cleared at the start of each new turn.
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
        self.add_column("icon",   width=2)
        self.add_column("name",   width=18)
        self.add_column("detail", width=8)

    def add_tool_row(self, index: int, name: str) -> None:
        """Called on tool_call_start — adds a spinner row."""
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

        icon_style  = "bright_green" if ok else "bright_red"
        detail_style = "bright_green" if ok else "bright_red"
        icon   = Text("✓" if ok else "✗", style=icon_style)
        detail = Text(row.detail,          style=detail_style)

        self.update_cell(str(index), "icon",   icon)
        self.update_cell(str(index), "detail", detail)

    def clear_rows(self) -> None:
        """Clear the panel at the start of a new turn."""
        self.clear()
        self._rows.clear()
```

### Step 2 — Update `AgentApp` to mount the tool panel (`src/tui/app.py`)

Add a horizontal split: the transcript takes the available width; the tool panel has a fixed width on the right.

```python
# src/tui/app.py

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.containers import Horizontal

from tui.components.transcript import TranscriptPane
from tui.components.tool_panel import ToolPanel


class AgentApp(App):
    """TUI with transcript + tool panel (Layer 10.3)."""

    CSS = """
    Screen {
        layout: vertical;
    }
    Horizontal {
        height: 1fr;
    }
    """

    def __init__(self, task: str) -> None:
        super().__init__()
        self.task = task

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield TranscriptPane(highlight=True, markup=False)
            yield ToolPanel()

    async def on_mount(self) -> None:
        from agent import run_agent
        asyncio.create_task(run_agent(self.task))

    def handle_agent_event(self, event: dict) -> None:
        t = event["type"]
        transcript = self.query_one(TranscriptPane)
        panel      = self.query_one(ToolPanel)

        if t == "text_delta":
            transcript.append_text(event["delta"])
        elif t == "tool_call_start":
            panel.add_tool_row(event["index"], event["name"])
        elif t == "tool_call_end":
            panel.finish_tool_row(
                event["index"],
                ok=not event["is_error"],
                chars=event["chars"],
            )
        elif t == "turn_end":
            # Clear the tool panel at the start of the next turn so it only
            # shows activity for the most recent set of tool calls.
            # We clear on turn_end rather than at the start of the next turn
            # so the user has a moment to read the results.
            pass   # defer clearing to the next tool_call_start if you prefer
        # agent_end handled in Layer 10.4
```

:::tip When to clear the panel
The panel shows the tool activity of the *most recent inner-loop turn*. Clearing on every `turn_end` removes results before the user can read them. A good heuristic: clear when the first `tool_call_start` of a new turn arrives (the panel resets naturally), or add a short delay. For this layer, leaving the last turn's results visible until new activity starts is fine.
:::

### Step 3 — No changes to `agent.py` or `renderer.py`

`tool_call_start` and `tool_call_end` events were already wired in Layer 10.1. The panel just handles them now. Verify by re-reading `handle_agent_event` — it was stubbed to ignore all non-`text_delta` events in Layer 10.2.

## Test it

### Behavior (BDD)

Verify this layer as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Scenario: Tool panel shows spinner and resolves on completion
  Given the agent is launched with AGENT_UI=tui
  When the agent executes a tool call during a run
  Then a row appears in the ToolPanel with a spinner icon when tool_call_start fires
  And the row's icon changes to ✓ and shows a char count when tool_call_end fires with is_error=False
  And the row's icon changes to ✗ when tool_call_end fires with is_error=True
```

Run this as an integration scenario with the [BDD framework](../../guides/bdd-integration-testing.md).

The scenario fails before this layer because `ToolPanel` does not exist and `handle_agent_event` ignores `tool_call_start` and `tool_call_end`. After the layer it passes because both events reach `ToolPanel.add_tool_row` and `finish_tool_row`.

:::tip Testing widget state
Use Textual's `Pilot` to drive a scripted agent run (via `ScriptedLLM` from Phase 9's test harness) and then assert:

```python
async with app.run_test() as pilot:
    await pilot.pause(0.5)
    panel = app.query_one(ToolPanel)
    assert panel.row_count == 1
    # check the cell value for the resolved icon
```
:::

## Run it

```bash
AGENT_UI=tui uv run main.py "read the file src/agent.py and summarise it"
```

You should see the transcript on the left streaming model text, and the tool panel on the right showing a `⏳ read_file` row that resolves to `✓ read_file  N,NNNc` when the tool returns.

If the agent calls multiple tools in one turn (e.g., Phase 7's parallel execution), you see multiple rows appear in rapid succession and resolve as each `tool_call_end` fires.

## Recap

The TUI now has two regions: a transcript pane for model text and a tool panel for live tool activity. Tool calls arrive as spinner rows and resolve to ✓ or ✗ with a char count.

The next layer rounds out the layout with an input box (for submitting tasks) and a status bar (model, iteration counter, elapsed time).

→ [Layer 10.4 — Input & Status Bar](./4-input-status.md)
