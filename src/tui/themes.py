# src/tui/themes.py

"""Named color schemes for the TUI.

Each theme maps semantic role names to Rich color strings. Widgets receive
the theme dict at construction time and look up roles by key — they never
hardcode colors.
"""

from __future__ import annotations

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "user": "bright_cyan",
        "assistant": "white",
        "tool_ok": "bright_green",
        "tool_error": "bright_red",
        "tool_name": "bright_yellow",
        "status": "grey70",
        "border": "grey42",
        "background": "default",
    },
    "light": {
        "user": "dark_cyan",
        "assistant": "black",
        "tool_ok": "dark_green",
        "tool_error": "dark_red",
        "tool_name": "dark_orange3",
        "status": "grey50",
        "border": "grey35",
        "background": "default",
    },
    "high_contrast": {
        "user": "bright_white",
        "assistant": "bright_white",
        "tool_ok": "bright_green",
        "tool_error": "bright_red",
        "tool_name": "bright_yellow",
        "status": "bright_white",
        "border": "bright_white",
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
