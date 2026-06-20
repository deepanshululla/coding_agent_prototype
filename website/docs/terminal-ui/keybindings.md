---
sidebar_position: 4
title: Keybindings
description: Vim-style modal keybindings for the Terminal UI — NORMAL / INSERT / COMMAND modes, the default keymap, how each binding maps to an app action, and how to customize.
---

# Keybindings

The TUI uses **Vim-style modal keybindings**. Like Vim, you are always in a mode: you *navigate* the transcript in **NORMAL** mode, *type* a steering message in **INSERT** mode, and run app commands in **COMMAND** mode. This keeps the home row doing navigation during a long run and reserves typing for when you actually have something to say to the agent.

:::note
Keybindings are part of the **planned TUI**, not yet implemented. This page documents the intended modal map and the customization hook.
:::

## Modes

| Mode | Enter it with | What it's for |
|---|---|---|
| **NORMAL** | `Esc` (default mode) | Navigate the transcript; issue motions |
| **INSERT** | `i` / `a` / `o` from NORMAL | Type a steering message in the input box |
| **COMMAND** | `:` from NORMAL | Run an app command (`:q`, `:clear`, …) |

The status bar shows the current mode (`-- NORMAL --`, `-- INSERT --`, `:…`), exactly like Vim.

## Default keymap

### NORMAL mode

| Key | Action | Description |
|---|---|---|
| `j` / `k` | Scroll down / up | Move the transcript one line |
| `Ctrl-d` / `Ctrl-u` | Half-page down / up | Scroll the transcript half a screen |
| `gg` | Jump to top | Scroll to the first line |
| `G` | Jump to bottom | Return to the live tail; re-enables auto-scroll |
| `/` | Search | Search the transcript; `n` / `N` for next / previous match |
| `i` / `a` / `o` | Insert | Focus the input box (enter INSERT mode) to write a steering message |
| `:` | Command | Enter COMMAND mode |
| `Ctrl-C` | Cancel turn | Signal the running turn to stop (works in any mode) |

### INSERT mode

| Key | Action | Description |
|---|---|---|
| `Esc` | Leave INSERT | Discard focus, return to NORMAL |
| `Enter` | Submit steering message | Send the input box text as a follow-up user message, return to NORMAL |
| _(text)_ | Edit | Standard Vi line editing inside the input box |

### COMMAND mode

| Command | Action |
|---|---|
| `:q` | Quit the TUI (terminates the agent) |
| `:w` | Submit the current input (alias for `Enter`) |
| `:clear` | Clear the visible transcript (history is untouched) |
| `:theme <name>` | Switch the [theme](./themes.md) at runtime |
| `Esc` | Cancel the command, return to NORMAL |

---

## How bindings map to actions

### `i` then `Enter` — submit a steering message

`i` (or `a`/`o`) switches to INSERT and focuses the input box. You type, then `Enter` posts an `InputBox.Submitted` message; the app appends `{"role": "user", "content": text}` to `pending_messages` and drops back to NORMAL. The outer loop in `run_agent` picks it up on its next check — this is the TUI's integration point with [Steering](../advanced/steering.md).

```
NORMAL  --i-->  INSERT  --type-->  --Enter-->  pending_messages.append({...})  --> NORMAL
```

### `j` / `k`, `Ctrl-d` / `Ctrl-u`, `gg` / `G` — navigate the transcript

These are routed to the `TranscriptPane` scroll handlers, mirroring Vim motions. Scrolling up (`k`, `Ctrl-u`, `gg`) suspends auto-scroll; `G` jumps to the live tail and re-enables it. `/` opens an incremental search with `n`/`N` to cycle matches.

### `Ctrl-C` — cancel the current turn

`Ctrl-C` works in **any** mode and does **not** raise `KeyboardInterrupt` (the framework intercepts it). It sets an `asyncio.Event` that `run_agent` checks at the top of each inner-loop iteration:

```python
# src/tui/app.py  (sketch)
import asyncio

class AgentApp(App):
    def __init__(self, task: str) -> None:
        super().__init__()
        self.task = task
        self.cancel_event = asyncio.Event()

    def action_cancel_turn(self) -> None:
        self.cancel_event.set()
```

```python
# Inside run_agent — the cancellation check point
while (has_more_tool_calls or pending_messages) and iteration < MAX_ITERATIONS:
    if cancel_event is not None and cancel_event.is_set():
        cancel_event.clear()
        break   # exit inner loop; outer loop waits for the next steering message
    ...
```

`run_agent` accepts `cancel_event` as an optional argument; under `AGENT_UI=stdout` it is `None` and the check is skipped.

:::warning
Cancelling mid-turn discards the assistant's current partial response and any in-flight tool calls. The message history up to the cancelled turn is intact and is sent to the model on the next steering message.
:::

### `:q` — quit

Calls `app.exit()`, which cancels all running Tasks (including the `run_agent` Task) and exits the asyncio loop cleanly.

---

## Implementing modal bindings

**prompt_toolkit** has first-class Vi support — turn it on and the input box gets Vi editing for free, then add navigation bindings gated by the Vi navigation (NORMAL) filter:

```python
from prompt_toolkit import Application
from prompt_toolkit.enums import EditingMode
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.filters import vi_navigation_mode

kb = KeyBindings()

@kb.add("j", filter=vi_navigation_mode)
def _scroll_down(event): transcript.scroll_down()

@kb.add("k", filter=vi_navigation_mode)
def _scroll_up(event): transcript.scroll_up()

@kb.add("g", "g", filter=vi_navigation_mode)
def _top(event): transcript.scroll_to_top()

@kb.add("G", filter=vi_navigation_mode)
def _bottom(event): transcript.scroll_to_tail()

@kb.add("c-c")            # any mode
def _cancel(event): app_state.cancel_event.set()

app = Application(key_bindings=kb, editing_mode=EditingMode.VI, full_screen=True)
```

**Textual** has no built-in Vi mode, so model it with a `mode` reactive and conditional bindings:

```python
from textual.app import App
from textual.binding import Binding

class AgentApp(App):
    mode = reactive("normal")          # "normal" | "insert" | "command"

    BINDINGS = [
        Binding("j", "scroll_down", "Down", show=False),
        Binding("k", "scroll_up", "Up", show=False),
        Binding("g,g", "scroll_top", "Top", show=False),
        Binding("G", "scroll_bottom", "Bottom", show=False),
        Binding("i", "enter_insert", "Insert"),
        Binding("colon", "enter_command", "Command"),
        Binding("escape", "enter_normal", "Normal"),
        Binding("ctrl+c", "cancel_turn", "Cancel"),
    ]

    def check_action(self, action: str, _) -> bool:
        # Motions only fire in NORMAL; let the input box own keys in INSERT.
        if self.mode == "insert" and action in {"scroll_down", "scroll_up", "scroll_top", "scroll_bottom"}:
            return False
        return True
```

---

## Customizing bindings

Override a binding by subclassing `AgentApp` and redeclaring `BINDINGS` (Textual) or adding to the `KeyBindings` registry (prompt_toolkit). There is no config file in the planned v1 — customization is code-level. To remap "jump to bottom" from `G` to `L`, say:

```python
from tui.app import AgentApp
from textual.binding import Binding

class MyAgentApp(AgentApp):
    BINDINGS = AgentApp.BINDINGS + [
        Binding("L", "scroll_bottom", "Bottom (custom)"),
    ]
```

---

## Related pages

- [Components](./components.md) — the input box and transcript pane that bindings act on
- [Themes](./themes.md) — `:theme` switches these at runtime
- [Steering](../advanced/steering.md) — how `pending_messages` and the outer loop work
- [Overview](./overview.md) — `AGENT_UI` env var and architecture
