---
sidebar_position: 1
title: Overview
description: Why a Terminal UI, what it adds over stdout, and how it plugs into the agent loop without changing the loop at all.
---

# Terminal UI

The v1 agent streams everything to stdout: tokens as they arrive, tool names as they're dispatched, brief completion lines after each tool returns. For a one-shot script that's fine. Once you're using the agent interactively — watching multi-turn runs, steering mid-task, or just wanting scrollback that doesn't blur past — a full-screen terminal interface is more useful.

The Terminal UI is an opt-in front-end over the **same agent loop**. It doesn't change `run_agent`, the tool dispatch, or the message history. It changes only what consumes the agent's events.

:::note
The Terminal UI is a **designed feature, not yet shipped**. v1 prints plain text to stdout. This section documents the architecture and planned component design so you can build it as a layer over the existing loop. Each page flags what is planned vs. implemented.
:::

## What it adds over stdout

| Capability | stdout (v1) | Terminal UI |
|---|---|---|
| Streamed text | Printed inline | Scrollable transcript pane |
| Tool calls | `▸ tool_name` printed once | Live panel: spinner → ✓/✗ per call |
| Steering input | Not supported in v1 | Input box at the bottom; messages queued into `pending_messages` |
| Status | None | Status bar: model, iteration N/MAX_ITERATIONS, elapsed time |
| Scrollback | Terminal's default scroll buffer | Managed pane; Ctrl-PgUp/Dn always works |
| Theme | Terminal default colors | Named color schemes via `AGENT_THEME` |

## The architectural principle

The UI is a **renderer of agent events**. The loop is the source of truth; the renderer is interchangeable.

This works because `run_agent`'s `print()` calls are replaced by a single `emit()` function — an event seam. Both the stdout renderer and the TUI consume the same five event types defined in the [JSON Event Stream schema](../programmatic-usage/json-event-stream.md):

- `text_delta` — a streamed text fragment
- `tool_call_start` — a tool call index first seen in the stream
- `tool_call_end` — a tool call completed with result
- `turn_end` — one inner-loop iteration finished
- `agent_end` — the outer loop exited

The stdout renderer turns those events back into human-readable lines. The TUI renderer routes them to widgets. Same events, different sinks.

```
                          ┌─────────────────┐
  task ──► run_agent ───► │   emit(event)   │
                          └────────┬────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
             AGENT_UI=stdout              AGENT_UI=tui
                    │                             │
           ┌────────▼────────┐        ┌───────────▼───────────┐
           │  stdout renderer│        │  TUI (prompt_toolkit /  │
           │  (plain text)   │        │  Textual full-screen)  │
           └─────────────────┘        └───────────────────────┘
```

## Enabling the TUI

Set `AGENT_UI=tui` before running the agent:

```bash
AGENT_UI=tui uv run main.py "refactor tools.py"
```

The default is `AGENT_UI=stdout`, which reproduces v1 behavior exactly. Selecting `tui` launches a full-screen prompt_toolkit (or Textual) application that drives `run_agent` on an asyncio event loop.

You can also set a color theme:

```bash
AGENT_UI=tui AGENT_THEME=light uv run main.py "explain the agent loop"
```

See [Themes](./themes.md) for the available color schemes.

## The `emit()` seam

The only change needed in `src/agent.py` is replacing each `print()` call with a call to `emit()`. The emitter is selected at startup based on `AGENT_UI`:

```python
import os

_UI = os.getenv("AGENT_UI", "stdout")

if _UI == "tui":
    from tui import emit  # TUI registers its own handler
else:
    from renderer_stdout import emit  # plain-text fallback
```

The stdout renderer is a thin function that reconstructs human-readable output from the event dict — exactly what v1 printed. The TUI renderer routes events to widgets in the running application.

See [Rendering the Stream](./rendering-the-stream.md) for the emit refactor in detail.

## Steering from the TUI

The outer loop in `run_agent` already supports follow-up messages via `pending_messages`. In v1 there is no input source wired in, so the outer loop runs exactly once. The TUI's input box is the natural place to wire in steering: the user types a message and presses Enter; the TUI pushes it into `pending_messages` and the outer loop picks it up on the next pass.

This is described in [Advanced / Steering](../advanced/steering.md), and the TUI's input box and keybindings for it are covered in [Keybindings](./keybindings.md).

## In this section

- [Rendering the Stream](./rendering-the-stream.md) — how text deltas and tool markers become live widget updates
- [Components](./components.md) — transcript pane, tool-activity panel, input box, status bar
- [Keybindings](./keybindings.md) — default keymap and how to customize it
- [Themes](./themes.md) — named color schemes and how to add your own
