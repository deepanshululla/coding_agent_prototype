---
sidebar_position: 2
title: "Layer 10.2 — The Transcript Pane"
description: Build a minimal Textual app with a scrolling transcript pane and wire it to the emit() seam via AGENT_UI=tui.
---

# Layer 10.2 — The Transcript Pane

:::note Starting point
The `emit()` seam and `StdoutRenderer` from Layer 10.1. Running `AGENT_UI=stdout uv run main.py "..."` produces identical output to Phase 9. The `renderer.py` selector exists but the `tui` branch raises `ImportError` because `src/tui/` doesn't exist yet.
:::

The event seam is wired. Now put something on the other end of it. This layer builds the **smallest possible TUI**: a single scrollable transcript pane that renders streamed text as it arrives, selected by `AGENT_UI=tui`. Nothing else — no tool panel, no input box, no status bar. Those come in later layers.

The transcript pane is the most important widget: it is always visible, always growing, and its rendering quality is what the user notices most. Getting it right first gives you a stable baseline for the layers that follow.

## What you'll learn

- How to bootstrap a Textual `App` as an asyncio host so `run_agent` runs as a Task inside it.
- How to implement `TuiRenderer.emit()` and route `text_delta` events to the pane.
- How to switch between the stdout and TUI renderers with `AGENT_UI`.
- Why auto-scroll is the right default and how Textual's `RichLog` gives it for free.

## Build it

### Step 1 — Create the `src/tui/` package

```bash
mkdir -p src/tui/components
touch src/tui/__init__.py src/tui/components/__init__.py
```

### Step 2 — The `TranscriptPane` widget (`src/tui/components/transcript.py`)

Textual's `RichLog` widget is an append-only scrollable log that auto-scrolls to the bottom on every write. That's exactly the behaviour you want: each `text_delta` appends to the bottom; the user sees the live tail.

```python
# src/tui/components/transcript.py

from textual.widgets import RichLog


class TranscriptPane(RichLog):
    """Append-only scrollable transcript of assistant output.

    Receives text_delta events from the TUI renderer and appends each
    fragment. Auto-scrolls to the bottom as new text arrives; suspends
    auto-scroll when the user presses PgUp, and resumes on PgDn/Ctrl-End.
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
```

`scroll_end=True` keeps the view pinned to the bottom while text is streaming in. Textual suspends that pin automatically when the user manually scrolls up.

### Step 3 — The `AgentApp` (`src/tui/app.py`)

The `App` is the asyncio host. It mounts the `TranscriptPane`, starts `run_agent` as a background Task, and exposes `handle_agent_event` so the renderer can push events in.

```python
# src/tui/app.py

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult

from tui.components.transcript import TranscriptPane


class AgentApp(App):
    """Minimal TUI: transcript pane only (Layer 10.2)."""

    CSS = """
    Screen {
        layout: vertical;
    }
    """

    def __init__(self, task: str) -> None:
        super().__init__()
        self.task = task

    def compose(self) -> ComposeResult:
        yield TranscriptPane(highlight=True, markup=False)

    async def on_mount(self) -> None:
        # Import here to avoid a circular dependency: agent imports renderer,
        # renderer imports tui.emit, tui.emit is set up before run_agent starts.
        from agent import run_agent
        asyncio.create_task(run_agent(self.task))

    def handle_agent_event(self, event: dict) -> None:
        t = event["type"]
        if t == "text_delta":
            self.query_one(TranscriptPane).append_text(event["delta"])
        # Other event types handled in later layers.
```

### Step 4 — The TUI `emit` function (`src/tui/emit.py`)

The renderer needs to call methods on the live `AgentApp` instance. A module-level reference is the simplest approach: `set_app` is called once at startup; `emit` uses it for the lifetime of the process.

```python
# src/tui/emit.py

from __future__ import annotations

_app: "AgentApp | None" = None


def set_app(app: "AgentApp") -> None:
    """Register the live app instance. Called once at startup."""
    global _app
    _app = app


def emit(event: dict) -> None:
    """Route an agent event to the running TUI app."""
    if _app is None:
        return
    _app.handle_agent_event(event)
```

### Step 5 — Wire app startup (`src/tui/__init__.py`)

```python
# src/tui/__init__.py

"""TUI entry point — call run() instead of AgentApp directly."""

from tui.app import AgentApp
from tui.emit import set_app


def run(task: str) -> None:
    """Launch the TUI and block until it exits."""
    app = AgentApp(task)
    set_app(app)
    app.run()
```

### Step 6 — Update `src/renderer.py` to resolve the TUI branch

```python
# src/renderer.py

import os

_UI = os.getenv("AGENT_UI", "stdout")

if _UI == "tui":
    from tui.emit import emit  # noqa: F401
else:
    from renderer_stdout import emit  # noqa: F401
```

### Step 7 — Update `main.py` to dispatch on `AGENT_UI`

```python
# main.py  (relevant section — replace the existing asyncio.run call)

import asyncio
import os
import sys

AGENT_UI = os.getenv("AGENT_UI", "stdout")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: uv run main.py <task>", file=sys.stderr)
        sys.exit(1)
    task = " ".join(sys.argv[1:])

    if AGENT_UI == "tui":
        from tui import run
        run(task)
    else:
        from agent import run_agent
        asyncio.run(run_agent(task))


if __name__ == "__main__":
    main()
```

:::note Install Textual
Add the dependency if you haven't already:

```bash
uv add textual
```
:::

## Test it

### Behavior (BDD)

Verify this layer as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Scenario: TUI transcript pane renders streamed text
  Given the agent is launched with AGENT_UI=tui
  When the agent processes a task that produces streamed text
  Then text_delta events are routed to the TranscriptPane widget
  And the text visible in the transcript pane is identical to the
      assistant content that would appear in a stdout run
  And the final message history contains the same messages as a stdout run
```

Run this as an integration scenario with the [BDD framework](../../guides/bdd-integration-testing.md).

The scenario fails before this layer because `from tui.emit import emit` raises `ModuleNotFoundError`. After the layer it passes because the `TuiRenderer` routes `text_delta` to the pane.

:::tip Testing Textual apps
Textual ships a `Pilot` test harness (`app.run_async()` in test mode) that lets you assert widget state without a real terminal. Use it to verify that `TranscriptPane.renderable` contains the expected text after a scripted agent run — no display required.
:::

## Run it

```bash
# Launch the TUI
AGENT_UI=tui uv run main.py "explain what the agent loop does in one sentence"
```

You should see a full-screen terminal app with a scrollable pane. Text appears in it character-by-character as the model streams its response. Press `Ctrl-C` or `q` to exit (Textual's built-in quit binding).

The stdout path is unchanged:

```bash
# Still works exactly as before
uv run main.py "explain what the agent loop does in one sentence"
```

## Recap

`AGENT_UI=tui` now launches a full-screen Textual app. Text deltas stream into a scrollable transcript pane in real time. The stdout path is untouched.

The transcript shows text. It doesn't yet show tool calls. The next layer adds a second region — a live tool panel — that renders tool activity alongside the transcript.

→ [Layer 10.3 — The Tool Panel](./3-tool-panel.md)
