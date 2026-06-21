# src/tui/__init__.py

"""TUI entry point — call run() instead of constructing AgentApp directly."""

from tui.app import AgentApp
from tui.emit import set_app


def run(task: str, hot_reload: bool = False, model: str | None = None) -> None:
    """Launch the TUI and block until it exits.

    pending_messages is a shared list passed by reference into both AgentApp
    (the input box appends to it) and run_agent (the outer loop reads it).
    hot_reload enables file watching and automatic restart on source changes.
    model overrides the AGENT_MODEL env var for this session.
    """
    pending: list[dict] = []
    app = AgentApp(task, pending, hot_reload=hot_reload, model=model)
    set_app(app)
    app.run()

    # Hot reload: trigger_reload() requests a restart by exiting the app rather
    # than execing mid-render (which would corrupt the terminal). Now that
    # app.run() has returned and Textual has restored the terminal, re-exec.
    if getattr(app, "_reload_requested", False):
        from tui.hot_reload import do_reload

        do_reload()
