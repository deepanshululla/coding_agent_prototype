# src/tui/__init__.py

"""TUI entry point — call run() instead of constructing AgentApp directly."""

from tui.app import AgentApp
from tui.emit import set_app


def run(task: str) -> None:
    """Launch the TUI and block until it exits.

    pending_messages is a shared list passed by reference into both AgentApp
    (the input box appends to it) and run_agent (the outer loop reads it).
    """
    pending: list[dict] = []
    app = AgentApp(task, pending)
    set_app(app)
    app.run()
