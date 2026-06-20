---
sidebar_position: 4
title: "Layer 10.4 — Input & Status Bar"
description: Add an input box for submitting tasks and a status bar showing the model name, iteration counter, and elapsed time.
---

# Layer 10.4 — Input & Status Bar

:::note Starting point
The transcript + tool panel app from Layer 10.3. `AGENT_UI=tui` shows a two-region layout. The app has no way to submit a task interactively and no ambient status information.
:::

The last two missing pieces of the four-region layout are the **input box** and the **status bar**. Together they make the TUI self-contained: the user can type a task and submit it without touching the command line, and the status bar shows at a glance what the agent is doing.

The input box also foreshadows **steering** (Phase 15): it pushes follow-up messages into `pending_messages`, which the outer loop already knows how to handle. You are not implementing multi-turn steering in this layer — you are wiring the input so that the infrastructure is ready when you need it.

## What you'll learn

- How to build a `StatusBar` widget that consumes `turn_end` and `agent_end` events.
- How to build an `InputBox` that submits a task on Enter and pushes it to `pending_messages`.
- How to pass `pending_messages` by reference from `main.py` through to the app so the input box can populate it.
- How the four-region layout is assembled in `AgentApp.compose()`.

## Build it

### Step 1 — The `StatusBar` widget (`src/tui/components/status_bar.py`)

The status bar is a single line pinned to the bottom of the screen. It reads from `turn_end` and `agent_end` events and updates a formatted label.

```python
# src/tui/components/status_bar.py

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

    def __init__(self, max_iterations: int = 30) -> None:
        super().__init__()
        self._model = os.getenv("AGENT_MODEL", "claude-sonnet-4-5")
        self._max   = max_iterations
        self._iter  = 0
        self._start = time.monotonic()
        self._done  = False
        self._cancelled = False

    def set_iteration(self, n: int) -> None:
        self._iter = n
        self._render()

    def set_done(self, total: int) -> None:
        self._iter = total
        self._done = True
        self._render()

    def set_cancelled(self) -> None:
        self._cancelled = True
        self._render()

    def _render(self) -> None:
        elapsed = int(time.monotonic() - self._start)
        if self._cancelled:
            state = "cancelled"
        elif self._done:
            state = f"done ({self._iter} iters)"
        else:
            state = f"iter {self._iter}/{self._max}"
        self.update(f" {self._model}  •  {state}  •  {elapsed}s")
```

### Step 2 — The `InputBox` widget (`src/tui/components/input_box.py`)

The input box captures Enter. When the user submits text it:
1. Posts an `InputBox.Submitted` message (Textual's event bus).
2. Clears itself.

The `AgentApp` handles the message and pushes the text into `pending_messages`.

```python
# src/tui/components/input_box.py

from textual.message import Message
from textual.widgets import Input


class InputBox(Input):
    """Single-line input for submitting a task or a steering follow-up.

    Pressing Enter posts InputBox.Submitted. The AgentApp handler appends
    the text to pending_messages so the outer loop can pick it up.
    """

    DEFAULT_CSS = """
    InputBox {
        height: 1;
        border: none;
        background: $surface;
    }
    """

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.value.strip():
            self.post_message(self.Submitted(event.value.strip()))
            self.clear()
```

### Step 3 — Update `AgentApp` for the full four-region layout (`src/tui/app.py`)

```python
# src/tui/app.py

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.containers import Horizontal

from tui.components.input_box  import InputBox
from tui.components.status_bar import StatusBar
from tui.components.tool_panel import ToolPanel
from tui.components.transcript import TranscriptPane


class AgentApp(App):
    """Full four-region TUI: transcript | tool panel / input box / status bar."""

    CSS = """
    Screen {
        layout: vertical;
    }
    Horizontal {
        height: 1fr;
    }
    """

    def __init__(self, task: str, pending_messages: list[dict]) -> None:
        super().__init__()
        self.task = task
        self._pending = pending_messages   # shared reference; outer loop reads this

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield TranscriptPane(highlight=True, markup=False)
            yield ToolPanel()
        yield InputBox(placeholder="Type a task and press Enter…")
        yield StatusBar()

    async def on_mount(self) -> None:
        from agent import run_agent
        # Pass pending_messages into run_agent so the outer loop can receive
        # steering messages from the input box.
        asyncio.create_task(run_agent(self.task, self._pending))

    def on_input_box_submitted(self, message: InputBox.Submitted) -> None:
        """Push the submitted text into pending_messages."""
        self._pending.append({"role": "user", "content": message.text})
        # Echo the user message in the transcript so they can see it.
        self.query_one(TranscriptPane).append_text(f"\n> {message.text}\n")

    def handle_agent_event(self, event: dict) -> None:
        t          = event["type"]
        transcript = self.query_one(TranscriptPane)
        panel      = self.query_one(ToolPanel)
        status     = self.query_one(StatusBar)

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
            status.set_iteration(event["iteration"])
        elif t == "agent_end":
            status.set_done(event["total_iterations"])
```

### Step 4 — Thread `pending_messages` through `run_agent`

`run_agent` already declares `pending_messages: list[dict] = []` internally. To let the input box populate it from outside, add it as an optional argument:

```diff
-async def run_agent(task: str) -> list[dict]:
+async def run_agent(task: str, pending_messages: list[dict] | None = None) -> list[dict]:
     system_prompt = build_system_prompt()
     messages: list[dict] = [{"role": "user", "content": task}]
-    pending_messages: list[dict] = []
+    if pending_messages is None:
+        pending_messages = []
```

Everything else in `run_agent` is unchanged — it still reads from and clears `pending_messages` on each inner-loop pass.

:::warning Backward compatibility
The `pending_messages` parameter is optional with a `None` default, so all existing callers (including the Phase 9 tests) continue to work without modification. `uv run pytest -q` must still pass 17 tests.
:::

### Step 5 — Update `src/tui/__init__.py`

```python
# src/tui/__init__.py

from tui.app import AgentApp
from tui.emit import set_app


def run(task: str) -> None:
    """Launch the TUI. pending_messages is shared between the app and run_agent."""
    pending: list[dict] = []
    app = AgentApp(task, pending)
    set_app(app)
    app.run()
```

## Test it

### Behavior (BDD)

Verify this layer as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Scenario: Input box starts a run and status bar tracks iterations
  Given the agent is launched with AGENT_UI=tui
  When the user types a task into the input box and presses Enter
  Then the task text is pushed into pending_messages
  And run_agent begins a new inner-loop pass with that task
  And the status bar shows "iter N/30" after each turn_end event fires
  And the status bar shows "done" after the agent_end event fires
```

Run this as an integration scenario with the [BDD framework](../../guides/bdd-integration-testing.md).

The scenario fails before this layer because `InputBox` and `StatusBar` do not exist, `handle_agent_event` ignores `turn_end` and `agent_end`, and `run_agent` does not accept `pending_messages`. After the layer it passes because all four widgets are wired and the signature change is in place.

### Regression check

```bash
uv run pytest -q
# 17 passed — pending_messages=None default preserves all existing tests
```

## Run it

```bash
AGENT_UI=tui uv run main.py "list the Python files in src/"
```

The layout now shows all four regions:

```
┌─────────────────────────────────┬──────────────────────┐
│  TranscriptPane                 │  ToolPanel           │
│  (streaming model text)         │  ⏳ list_dir         │
│                                 │  ✓ list_dir  42c     │
├─────────────────────────────────┴──────────────────────┤
│  Type a task and press Enter…                          │
├────────────────────────────────────────────────────────┤
│  claude-sonnet-4-5  •  iter 2/30  •  8s               │
└────────────────────────────────────────────────────────┘
```

The status bar updates the iteration counter as each inner-loop pass completes. When the agent finishes it shows `done (N iters)`.

## Recap

The TUI now has all four regions. The input box can submit tasks and foreshadows steering; the status bar tracks progress across iterations. The outer loop is ready to accept follow-up messages via `pending_messages`.

The last layer adds interactivity: keybindings (Ctrl-C cancel, Ctrl-D quit, PgUp/PgDn scroll) and themes via `AGENT_THEME`.

→ [Layer 10.5 — Keybindings & Themes](./5-keys-themes.md)
