---
sidebar_position: 5
title: "Layer 10.5 — Keybindings & Themes"
description: Add Vim-style modal keybindings (NORMAL/INSERT/COMMAND modes), cooperative Ctrl-C cancel, and AGENT_THEME color schemes to complete the terminal UI.
---

# Layer 10.5 — Keybindings & Themes

:::note Starting point
The full four-region app from Layer 10.4: transcript pane, tool panel, input box, and status bar. `AGENT_UI=tui` launches a fully laid-out app, but there are no keybindings beyond Textual's built-ins and no way to change the color scheme.
:::

This is the last layer in Phase 10. It adds two things that turn the app from a demo into a tool you can actually use:

- **Keybindings** — Vim-style modal keybindings: `j`/`k` scroll the transcript in NORMAL mode, `i` enters INSERT mode to type a steering message, `Esc` returns to NORMAL, `:q` quits, and `Ctrl-C` cancels the in-flight turn from any mode without killing the process.
- **Themes** — `AGENT_THEME=light` (or `dark` / `high_contrast`) swaps the color role dict used by all widgets. Colors are semantic — "tool OK", "user text", "border" — not hardcoded hex values.

Both are additive deltas over Layer 10.4's files. The loop does not change.

For the full design rationale, see [Keybindings](../../terminal-ui/keybindings.md) and [Themes](../../terminal-ui/themes.md).

## What you'll learn

- How modal keybindings work: `j`/`k` scroll the transcript, `i` enters INSERT mode to type a steering message, `Esc` returns to NORMAL, and `:q` quits via COMMAND mode.
- How `Ctrl-C` becomes a cooperative cancel rather than a `KeyboardInterrupt` via an `asyncio.Event`, and works in any mode.
- How `run_agent` checks that event at the top of each inner-loop pass.
- How a `THEMES` dict with semantic color roles decouples colors from widgets.
- How to pass the active theme dict to each widget at construction time.

## Build it

### Step 1 — Create `src/tui/themes.py`

```python
# src/tui/themes.py

"""Named color schemes for the TUI.

Each theme maps semantic role names to Rich color strings. Widgets receive
the theme dict at construction time and look up roles by key — they never
hardcode colors.
"""

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "user":       "bright_cyan",
        "assistant":  "white",
        "tool_ok":    "bright_green",
        "tool_error": "bright_red",
        "tool_name":  "bright_yellow",
        "status":     "grey70",
        "border":     "grey42",
        "background": "default",
    },
    "light": {
        "user":       "dark_cyan",
        "assistant":  "black",
        "tool_ok":    "dark_green",
        "tool_error": "dark_red",
        "tool_name":  "dark_orange3",
        "status":     "grey50",
        "border":     "grey35",
        "background": "default",
    },
    "high_contrast": {
        "user":       "bright_white",
        "assistant":  "bright_white",
        "tool_ok":    "bright_green",
        "tool_error": "bright_red",
        "tool_name":  "bright_yellow",
        "status":     "bright_white",
        "border":     "bright_white",
        "background": "default",
    },
}

_FALLBACK = "dark"


def get_theme(name: str) -> dict[str, str]:
    """Return the theme dict for *name*, falling back to 'dark' with a warning."""
    if name not in THEMES:
        import sys
        print(f"[tui] unknown theme {name!r}, using 'dark'", file=sys.stderr)
        name = _FALLBACK
    return THEMES[name]
```

### Step 2 — Add `cancel_event` to `run_agent` (`src/agent.py`)

`run_agent` accepts an optional `asyncio.Event`. At the top of each inner-loop pass it checks the event; if set, it clears it and breaks out of the inner loop. The outer loop then waits for more `pending_messages` — it does not terminate.

```diff
-async def run_agent(task: str, pending_messages: list[dict] | None = None) -> list[dict]:
+async def run_agent(
+    task: str,
+    pending_messages: list[dict] | None = None,
+    cancel_event: asyncio.Event | None = None,
+) -> list[dict]:
     system_prompt = build_system_prompt()
     messages: list[dict] = [{"role": "user", "content": task}]
     if pending_messages is None:
         pending_messages = []

     while True:
         has_more_tool_calls = True
         iteration = 0

         while (has_more_tool_calls or pending_messages) and iteration < MAX_ITERATIONS:
+            # Cooperative cancel: Ctrl-C in the TUI sets this event.
+            if cancel_event is not None and cancel_event.is_set():
+                cancel_event.clear()
+                emit({"type": "agent_cancelled"})
+                break   # exit inner loop; outer loop waits for input
+
             iteration += 1
             ...
```

The `cancel_event` is `None` in stdout mode and in all existing tests — the check is skipped, preserving backward compatibility.

### Step 3 — Update `AgentApp` with modal bindings and the cancel event (`src/tui/app.py`)

The app tracks a `mode` reactive (`"normal"` / `"insert"` / `"command"`) and uses `check_action` to gate scroll motions to NORMAL mode only — the same pattern described in [Keybindings](../../terminal-ui/keybindings.md).

```python
# src/tui/app.py

from __future__ import annotations

import asyncio
import os

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive

from tui.components.input_box  import InputBox
from tui.components.status_bar import StatusBar
from tui.components.tool_panel import ToolPanel
from tui.components.transcript import TranscriptPane
from tui.themes import get_theme


class AgentApp(App):
    """Full TUI with Vim-style modal keybindings and themes (Layer 10.5)."""

    mode: reactive[str] = reactive("normal")  # "normal" | "insert" | "command"

    BINDINGS = [
        Binding("j",       "scroll_down",    "Down",    show=False),
        Binding("k",       "scroll_up",      "Up",      show=False),
        Binding("g,g",     "scroll_top",     "Top",     show=False),
        Binding("G",       "scroll_bottom",  "Bottom",  show=False),
        Binding("i",       "enter_insert",   "Insert",  show=True),
        Binding("colon",   "enter_command",  "Command", show=True),
        Binding("escape",  "enter_normal",   "Normal",  show=False),
        Binding("ctrl+c",  "cancel_turn",    "Cancel",  show=True),
    ]

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
        self.task         = task
        self._pending     = pending_messages
        self.cancel_event = asyncio.Event()
        self.theme_dict   = get_theme(os.getenv("AGENT_THEME", "dark"))

    def check_action(self, action: str, parameters: object) -> bool:
        # Scroll motions only fire in NORMAL; INSERT owns the keyboard for typing.
        if self.mode == "insert" and action in {
            "scroll_down", "scroll_up", "scroll_top", "scroll_bottom"
        }:
            return False
        return True

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield TranscriptPane(
                highlight=True, markup=False, theme=self.theme_dict
            )
            yield ToolPanel(theme=self.theme_dict)
        yield InputBox(placeholder="Type a steering message and press Enter…")
        yield StatusBar(theme=self.theme_dict)

    async def on_mount(self) -> None:
        from agent import run_agent
        asyncio.create_task(
            run_agent(self.task, self._pending, self.cancel_event)
        )

    # ── Mode actions ─────────────────────────────────────────────────────────

    def action_enter_insert(self) -> None:
        self.mode = "insert"
        self.query_one(InputBox).focus()

    def action_enter_command(self) -> None:
        self.mode = "command"

    def action_enter_normal(self) -> None:
        self.mode = "normal"
        self.query_one(TranscriptPane).focus()

    # ── Scroll actions (NORMAL mode only, gated by check_action) ─────────────

    def action_scroll_down(self) -> None:
        self.query_one(TranscriptPane).scroll_down()

    def action_scroll_up(self) -> None:
        self.query_one(TranscriptPane).scroll_up()

    def action_scroll_top(self) -> None:
        self.query_one(TranscriptPane).scroll_home()

    def action_scroll_bottom(self) -> None:
        self.query_one(TranscriptPane).scroll_end()

    # ── Cancel action (any mode) ──────────────────────────────────────────────

    def action_cancel_turn(self) -> None:
        """Signal the running inner loop to stop after the current iteration."""
        self.cancel_event.set()
        # Status bar will update when agent_cancelled event arrives.

    # ── Event handlers ────────────────────────────────────────────────────────

    def on_input_box_submitted(self, message: InputBox.Submitted) -> None:
        self._pending.append({"role": "user", "content": message.text})
        self.query_one(TranscriptPane).append_text(f"\n> {message.text}\n")
        self.action_enter_normal()   # return to NORMAL after submitting

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
        elif t == "agent_cancelled":
            status.set_cancelled()
```

### Step 4 — Pass `theme` into each widget

Each widget accepts the theme dict at construction time. Update `ToolPanel` and `StatusBar` to apply color roles:

```python
# src/tui/components/tool_panel.py  — updated finish_tool_row

def __init__(self, theme: dict[str, str] | None = None) -> None:
    super().__init__(show_header=False, show_cursor=False)
    self._rows:  dict[int, _ToolRow] = {}
    self._theme = theme or {}

def finish_tool_row(self, index: int, ok: bool, chars: int) -> None:
    if index not in self._rows:
        return
    role   = "tool_ok" if ok else "tool_error"
    color  = self._theme.get(role, "white")
    icon   = Text("✓" if ok else "✗",                  style=color)
    detail = Text(f"{chars:,}c" if ok else "err",       style=color)
    self.update_cell(str(index), "icon",   icon)
    self.update_cell(str(index), "detail", detail)
```

```python
# src/tui/components/status_bar.py  — updated __init__ and _render

def __init__(self, max_iterations: int = 30, theme: dict[str, str] | None = None) -> None:
    super().__init__()
    self._model  = os.getenv("AGENT_MODEL", "claude-sonnet-4-5")
    self._max    = max_iterations
    self._iter   = 0
    self._start  = time.monotonic()
    self._done   = False
    self._cancelled = False
    self._color  = (theme or {}).get("status", "grey70")

def _render(self) -> None:
    from rich.text import Text
    elapsed = int(time.monotonic() - self._start)
    if self._cancelled:
        state = "cancelled"
    elif self._done:
        state = f"done ({self._iter} iters)"
    else:
        state = f"iter {self._iter}/{self._max}"
    line = f" {self._model}  •  {state}  •  {elapsed}s"
    self.update(Text(line, style=self._color))
```

`TranscriptPane` uses its theme for the user-message color (the `> ` prefix). Add a `theme` parameter to its `__init__` and store it for use in `append_text` if you want styled user messages; the assistant text can remain unstyled for readability.

### Step 5 — No changes to `renderer.py`, `renderer_stdout.py`, or `main.py`

The stdout path is unaffected. `AGENT_THEME` is ignored unless `AGENT_UI=tui`.

## Test it

### Behavior (BDD)

Verify this layer as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Scenario: Vim-style modal keybindings and theme env var changes colors
  Given the agent is launched with AGENT_UI=tui and the app starts in NORMAL mode
  When the user presses `j` then `k`
  Then the transcript scrolls down then up
  And pressing `i` switches to INSERT mode and focuses the input box
  And typing a follow-up message then pressing Enter queues a steering message and returns to NORMAL mode
  And pressing Ctrl-C during a run cancels the in-flight turn and the status bar shows "cancelled"
  And setting AGENT_THEME=light changes the ToolPanel "tool_ok" color to the light theme value
  And setting AGENT_THEME=light changes the StatusBar "status" color to the light theme value
```

Run this as an integration scenario with the [BDD framework](../../guides/bdd-integration-testing.md).

The scenario fails before this layer because `BINDINGS` does not define `j`, `k`, `i`, `escape`, or `colon`; `mode` reactive and `check_action` do not exist on `AgentApp`; `cancel_event` does not exist on `AgentApp`; `run_agent` does not accept `cancel_event`; and `get_theme` / `THEMES` do not exist. After the layer all of those are in place.

### Regression check

```bash
uv run pytest -q
# 17 passed — cancel_event=None default preserves all existing tests
```

## Run it

```bash
# Dark theme (default)
AGENT_UI=tui uv run main.py "read src/agent.py and list the public functions"

# Light theme
AGENT_UI=tui AGENT_THEME=light uv run main.py "read src/agent.py and list the public functions"

# High contrast
AGENT_UI=tui AGENT_THEME=high_contrast uv run main.py "read src/agent.py and list the public functions"
```

The app starts in NORMAL mode. Press `j`/`k` to scroll the transcript. Press `i` to enter INSERT mode, type a steering message, and press `Enter` to send it (the app returns to NORMAL automatically). Press `Ctrl-C` while the model is streaming to cancel the in-flight turn — the status bar shows `cancelled` within one iteration and the process stays alive. Enter `:q` in COMMAND mode (press `:` then type `q` and `Enter`) to exit cleanly.

## Recap

Phase 10 is complete. Here is what you built, layer by layer, without ever changing the agent loop:

| Layer | What was added |
|-------|---------------|
| 10.1 | `emit()` seam + `StdoutRenderer` (backward compatible) |
| 10.2 | Textual app + `TranscriptPane` + `AGENT_UI=tui` |
| 10.3 | `ToolPanel` with spinner rows resolving to ✓/✗ |
| 10.4 | `InputBox` + `StatusBar` + `pending_messages` wiring |
| 10.5 | Vim-style modal keybindings (NORMAL/INSERT/COMMAND) + `AGENT_THEME` |

The loop (`run_agent`) received three small, backward-compatible additions: `pending_messages` parameter (Layer 10.4), `cancel_event` parameter (10.5), and the `emit()` calls (10.1). It is otherwise unchanged.

The next phase swaps the `claude -p` CLI backend for **LiteLLM**, giving you access to any model provider — the same loop, a different provider layer.

→ [Phase 11 — Add LiteLLM](../11-add-litellm.md)
