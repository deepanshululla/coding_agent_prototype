---
sidebar_position: 3
title: Components
description: The building blocks of the Terminal UI — transcript pane, tool-activity panel, input box, and status bar — and which agent events drive each one.
---

# Components

The TUI is composed of four widgets. Each one is a pure consumer of agent events; none of them call into `run_agent` or read from stdout. The layout places the transcript and tool panel side-by-side in the main area, with the input box and status bar pinned to the bottom.

:::note
These components are **planned**, not yet implemented. v1 uses plain stdout. This page describes the design so you can build the layout incrementally — each widget is independent.
:::

```
┌─────────────────────────────────┬──────────────────────┐
│                                 │                      │
│        TranscriptPane           │     ToolPanel        │
│                                 │                      │
│  (scrollable assistant text)    │  (live tool rows)    │
│                                 │                      │
├─────────────────────────────────┴──────────────────────┤
│  InputBox  >                                           │
├────────────────────────────────────────────────────────┤
│  StatusBar  model • iter 2/30 • 14s                    │
└────────────────────────────────────────────────────────┘
```

## Component → event mapping

| Component | Event(s) consumed | What it does |
|---|---|---|
| `TranscriptPane` | `text_delta` | Appends each delta to a scrollable text buffer |
| `ToolPanel` | `tool_call_start`, `tool_call_end` | Adds a row on start (spinner), updates it on end (✓/✗) |
| `InputBox` | _(user input only)_ | Captures Enter keypress; pushes message to `pending_messages` |
| `StatusBar` | `turn_end`, `agent_end` | Updates iteration count and elapsed time |

---

## TranscriptPane

The transcript pane renders the full assistant text as it streams in. It is a read-only scrollable buffer.

```python
# src/tui/components/transcript.py  (Textual sketch)

from textual.widgets import RichLog

class TranscriptPane(RichLog):
    """Append-only scrollable transcript of assistant output."""

    def append_text(self, delta: str) -> None:
        # write() appends without a newline; auto-scrolls to bottom.
        self.write(delta, expand=True, scroll_end=True)
```

The pane auto-scrolls to the bottom as new text arrives. When the user presses PgUp to read earlier output, auto-scroll is suspended until they press PgDn or Ctrl-End to return to the bottom.

**Design notes:**
- Render text as plain text by default; optionally apply Markdown rendering for code blocks.
- Do not clear the pane between iterations — the full conversation history is visible.
- User messages submitted via the input box appear in the transcript too, prefixed with a `> ` prompt marker in the user color from the active theme.

---

## ToolPanel

The tool panel shows one row per tool call in the current turn. Each row transitions through three states:

1. **Pending** — tool name visible, spinner animating (between `tool_call_start` and `tool_call_end`)
2. **OK** — spinner replaced with ✓, char count shown
3. **Error** — spinner replaced with ✗, error color from theme

```python
# src/tui/components/tool_panel.py  (Textual sketch)

from dataclasses import dataclass, field
from textual.widgets import DataTable
from textual.reactive import reactive

@dataclass
class ToolRow:
    index: int
    name: str
    status: str = "pending"   # "pending" | "ok" | "error"
    detail: str = ""

class ToolPanel(DataTable):
    """Live tool-call status table."""

    _rows: dict[int, ToolRow] = field(default_factory=dict)

    def add_row(self, index: int, name: str) -> None:
        row = ToolRow(index=index, name=name)
        self._rows[index] = row
        super().add_row("⏳", name, "", key=str(index))

    def finish_row(self, index: int, ok: bool, chars: int) -> None:
        row = self._rows[index]
        row.status = "ok" if ok else "error"
        row.detail = f"{chars:,} chars" if ok else "error"
        icon = "✓" if ok else "✗"
        self.update_cell(str(index), "status", icon)
        self.update_cell(str(index), "detail", row.detail)
```

**Design notes:**
- Clear the tool panel at the start of each new turn (on `turn_end` with `finish_reason="tool_calls"`), not between iterations, so the user can see the last turn's tool activity while the model is generating the next response.
- Tool argument previews are shown only after `tool_call_end` arrives (when arguments are fully parsed). Do not attempt to render partial JSON during streaming.

---

## InputBox

The input box lives at the bottom of the screen. It is active only when the agent is between turns (i.e., after `agent_end` or while the outer loop is waiting for `pending_messages`). In v1 the outer loop does not wait for input; enabling it requires wiring the input box to `pending_messages` as described in [Steering](../advanced/steering.md).

```python
# src/tui/components/input_box.py  (Textual sketch)

from textual.widgets import Input
from textual.message import Message

class InputBox(Input):
    """Single-line input for steering messages."""

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.value.strip():
            self.post_message(self.Submitted(event.value.strip()))
            self.clear()
```

The `AgentApp` listens for `InputBox.Submitted` and pushes the text into `pending_messages`:

```python
# inside AgentApp

def on_input_box_submitted(self, message: InputBox.Submitted) -> None:
    self._pending_messages.append(
        {"role": "user", "content": message.text}
    )
```

The input box is disabled while a turn is actively streaming (between `turn_end` events) and re-enabled on `agent_end`.

---

## StatusBar

The status bar is a single line pinned to the bottom, above the input box. It displays ambient context the user can glance at without interrupting their reading of the transcript.

```python
# src/tui/components/status_bar.py  (Textual sketch)

import time
from textual.widgets import Static

class StatusBar(Static):
    """Ambient status: model, iteration, elapsed time."""

    def __init__(self, model: str, max_iterations: int) -> None:
        super().__init__()
        self._model = model
        self._max = max_iterations
        self._iteration = 0
        self._start = time.monotonic()
        self._done = False

    def set_iteration(self, n: int) -> None:
        self._iteration = n
        self._render()

    def set_done(self, total: int) -> None:
        self._iteration = total
        self._done = True
        self._render()

    def _render(self) -> None:
        elapsed = int(time.monotonic() - self._start)
        state = "done" if self._done else f"iter {self._iteration}/{self._max}"
        self.update(
            f" {self._model}  •  {state}  •  {elapsed}s"
        )
```

Fields shown in the status bar:

| Field | Source |
|---|---|
| Model name | `AGENT_MODEL` env var or hardcoded default |
| Iteration | `turn_end.iteration` |
| Max iterations | `MAX_ITERATIONS` constant (30) |
| Elapsed time | Wall clock from agent start |

---

## Related pages

- [Rendering the Stream](./rendering-the-stream.md) — the emit refactor and event dispatch
- [Keybindings](./keybindings.md) — keyboard actions that drive the input box and scroll
- [Themes](./themes.md) — color roles consumed by each component
- [Steering](../advanced/steering.md) — wiring the input box to `pending_messages`
