# src/tui/__init__.py

"""TUI entry point — call run() instead of constructing AgentApp directly."""

from tui.app import AgentApp
from tui.emit import set_app


def run(task: str, hot_reload: bool = False) -> None:
    """Launch the TUI and block until it exits.

    pending_messages is a shared list passed by reference into both AgentApp
    (the input box appends to it) and run_agent (the outer loop reads it).
    hot_reload enables file watching and automatic restart on source changes.
    """
    pending: list[dict] = []
    app = AgentApp(task, pending, hot_reload=hot_reload)
    set_app(app)
    app.run()
