# src/tui/emit.py

"""The TUI end of the emit() seam.

A module-level reference to the live AgentApp lets renderer.emit() push
events into the running app. set_app() is called once at startup; emit()
uses it for the lifetime of the process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Imported for typing only; app.py imports this module at runtime, so a real
    # import here would be circular.
    from tui.app import AgentApp

_app: AgentApp | None = None


def set_app(app: AgentApp) -> None:
    """Register the live app instance. Called once at startup."""
    global _app
    _app = app


def emit(event: dict) -> None:
    """Route an agent event to the running TUI app."""
    if _app is None:
        return
    _app.handle_agent_event(event)
