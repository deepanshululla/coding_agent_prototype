# src/tui/__init__.py

"""TUI entry point — call run() instead of constructing AgentApp directly."""

from tui.app import AgentApp
from tui.emit import set_app


def run(task: str) -> None:
    """Launch the TUI and block until it exits."""
    app = AgentApp(task)
    set_app(app)
    app.run()
