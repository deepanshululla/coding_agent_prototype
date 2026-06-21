# tests/conftest.py

"""Shared test fixtures and configuration."""

import sys

import pytest


@pytest.fixture(autouse=True)
def clear_tui_app():
    """Clear the global TUI app state before and after each test.

    The TUI emit system uses a module-level _app reference. When tests that
    use set_app() run, they register an app instance globally. This persists
    across tests and can cause later tests (e.g., agent tests that emit events)
    to fail when they try to route events to a now-unmounted app.

    This fixture ensures _app is None before each test starts and after it ends.

    Only clears if tui.emit has already been imported to avoid inadvertently
    triggering renderer selection in tests that don't use the TUI.
    """
    # Only clear if the module was already imported
    if "tui.emit" in sys.modules:
        import tui.emit

        tui.emit._app = None

    yield

    # Clear after test if it was imported during the test
    if "tui.emit" in sys.modules:
        import tui.emit

        tui.emit._app = None
