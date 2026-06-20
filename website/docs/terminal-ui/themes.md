---
sidebar_position: 5
title: Themes
description: Theming the Terminal UI via AGENT_THEME — named color schemes, color role definitions, and how to add a custom theme.
---

# Themes

The TUI uses a small color scheme dict to separate colors from widget code. Each theme maps semantic roles — "user message", "tool error", "status text" — to terminal color values. You select a theme with the `AGENT_THEME` environment variable.

:::note
Themes are part of the **planned TUI**, not yet implemented. This page documents the scheme structure and the planned selection mechanism.
:::

## Selecting a theme

```bash
AGENT_UI=tui AGENT_THEME=light uv run main.py "list all .py files"
```

`AGENT_THEME` defaults to `"dark"` when omitted. Unknown theme names fall back to `"dark"` with a warning on stderr.

---

## Color roles

Each theme defines values for these roles:

| Role | Where it's used |
|---|---|
| `user` | User messages in the transcript pane; `>` prefix in the input box |
| `assistant` | Assistant text in the transcript pane |
| `tool_ok` | ✓ icon and char count in the tool panel |
| `tool_error` | ✗ icon and error text in the tool panel |
| `tool_name` | Tool name text in the tool panel |
| `status` | Model name, iteration counter, elapsed time in the status bar |
| `border` | Widget borders and dividers |
| `background` | Application background |

---

## Built-in themes

```python
# src/tui/themes.py

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
    if name not in THEMES:
        import sys
        print(f"[tui] unknown theme {name!r}, using 'dark'", file=sys.stderr)
        name = _FALLBACK
    return THEMES[name]
```

Color names follow the Rich / prompt_toolkit color vocabulary (e.g., `"bright_green"`, `"grey70"`). Terminal-default colors use `"default"` so they inherit the user's terminal background.

---

## How a component reads the theme

The active theme dict is passed to each widget at construction time. Components look up roles by key:

```python
# src/tui/app.py  (sketch)

import os
from tui.themes import get_theme

class AgentApp(App):
    def __init__(self, task: str) -> None:
        super().__init__()
        self.task = task
        self.theme = get_theme(os.getenv("AGENT_THEME", "dark"))
```

```python
# src/tui/components/tool_panel.py  (sketch)

from rich.text import Text

class ToolPanel(DataTable):
    def __init__(self, theme: dict[str, str]) -> None:
        super().__init__()
        self._theme = theme

    def finish_row(self, index: int, ok: bool, chars: int) -> None:
        role = "tool_ok" if ok else "tool_error"
        color = self._theme[role]
        icon = Text("✓" if ok else "✗", style=color)
        detail = Text(f"{chars:,} chars" if ok else "error", style=color)
        self.update_cell(str(index), "status", icon)
        self.update_cell(str(index), "detail", detail)
```

---

## Adding a custom theme

Add an entry to `THEMES` in `src/tui/themes.py`:

```python
THEMES["solarized"] = {
    "user":       "steel_blue1",
    "assistant":  "grey93",
    "tool_ok":    "chartreuse3",
    "tool_error": "indian_red",
    "tool_name":  "dark_goldenrod",
    "status":     "grey58",
    "border":     "grey42",
    "background": "default",
}
```

Then select it:

```bash
AGENT_UI=tui AGENT_THEME=solarized uv run main.py "explain the agent loop"
```

No other changes are needed — `get_theme("solarized")` will find it and return the dict.

:::tip
Rich's color names are the easiest way to pick values. Run `python -m rich.color` in your terminal to see a full palette rendered in your terminal's actual colors.
:::

---

## prompt_toolkit color syntax

If you implement the TUI with prompt_toolkit rather than Textual, the color vocabulary differs slightly. prompt_toolkit uses CSS-style hex or named colors:

```python
# prompt_toolkit equivalent
THEMES["dark"] = {
    "user":       "#00d7ff",   # bright_cyan in hex
    "assistant":  "white",
    "tool_ok":    "#5fff00",
    "tool_error": "#ff0000",
    "tool_name":  "#ffff00",
    "status":     "#b2b2b2",
    "border":     "#6c6c6c",
    "background": "",          # empty string = terminal default
}
```

The role structure is identical; only the color string format changes. Keep a single `THEMES` dict and normalize at construction time based on which framework is in use.

---

## Related pages

- [Overview](./overview.md) — AGENT_THEME env var and AGENT_UI selection
- [Components](./components.md) — where each color role appears in the layout
- [Rendering the Stream](./rendering-the-stream.md) — how components receive and display events
