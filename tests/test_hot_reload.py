"""Tests for TUI hot reload feature."""

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import Mock


def test_hot_reload_flag_parsing():
    """--hot-reload flag should be extracted and passed through."""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from main import _extract_hot_reload

    # Flag present
    args, hot_reload = _extract_hot_reload(["--hot-reload", "my task"])
    assert hot_reload is True
    assert args == ["my task"]

    # Flag absent
    args, hot_reload = _extract_hot_reload(["my task"])
    assert hot_reload is False
    assert args == ["my task"]

    # Flag with other flags
    args, hot_reload = _extract_hot_reload(["--model", "gpt-4", "--hot-reload", "task"])
    assert hot_reload is True
    assert args == ["--model", "gpt-4", "task"]


def test_env_var_enables_hot_reload(monkeypatch):
    """AGENT_HOT_RELOAD=1 should enable hot reload."""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from main import _should_enable_hot_reload

    # Env var set
    monkeypatch.setenv("AGENT_HOT_RELOAD", "1")
    assert _should_enable_hot_reload(flag=False) is True

    # Flag takes precedence
    assert _should_enable_hot_reload(flag=True) is True

    # Neither set
    monkeypatch.delenv("AGENT_HOT_RELOAD", raising=False)
    assert _should_enable_hot_reload(flag=False) is False


def test_state_serialization(tmp_path):
    """save_tui_state and load_tui_state should round-trip."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from tui.hot_reload import load_tui_state, save_tui_state

    # Create a mock app with minimal state
    mock_app = Mock()
    mock_app._agent_task = "test task"

    # Mock transcript
    mock_transcript = Mock()
    mock_transcript.get_text.return_value = "assistant output\nmore text"
    mock_app.query_one = Mock(return_value=mock_transcript)

    # Save state
    state_file = save_tui_state(mock_app)
    assert state_file.exists()

    # Load state
    loaded = load_tui_state()
    assert loaded is not None
    assert loaded["task"] == "test task"
    assert "transcript" in loaded
    assert loaded["transcript"] == "assistant output\nmore text"


def test_load_missing_state():
    """load_tui_state should return None when no state file exists."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    import glob

    from tui.hot_reload import load_tui_state

    # Clean up any existing state
    for f in glob.glob("/tmp/tui-hot-reload-state-*.json"):
        try:
            os.remove(f)
        except OSError:
            pass

    assert load_tui_state() is None


def test_stale_state_ignored():
    """State older than 1 hour should be ignored."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from tui.hot_reload import load_tui_state

    state_file = Path(f"/tmp/tui-hot-reload-state-{os.getpid()}.json")
    # Create state with old timestamp
    old_state = {
        "task": "old task",
        "transcript": "old transcript",
        "timestamp": time.time() - 3700,  # 1 hour + 100 seconds ago
    }
    state_file.write_text(json.dumps(old_state))

    # Should be ignored due to age
    loaded = load_tui_state()
    assert loaded is None

    # Clean up
    state_file.unlink(missing_ok=True)


def test_trigger_reload_exits_without_execv_mid_run(monkeypatch):
    """trigger_reload must NOT os.execv while Textual owns the terminal — that
    skips teardown and corrupts the terminal. It sets a flag and exits instead."""
    import asyncio

    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    import tui.hot_reload as hr
    from tui.app import AgentApp

    execv_calls = []
    monkeypatch.setattr(hr.os, "execv", lambda *a: execv_calls.append(a))
    monkeypatch.setattr(hr, "save_tui_state", lambda app: None)  # no /tmp writes

    async def _run():
        app = AgentApp("task", hot_reload=True)
        async with app.run_test():
            app.trigger_reload()
        return app

    app = asyncio.run(_run())
    assert app._reload_requested is True
    assert execv_calls == []  # never execed while the app held the terminal


def test_run_reexecs_after_app_exits_when_reload_requested(monkeypatch):
    """run() performs the re-exec AFTER app.run() returns (terminal restored),
    and only when a reload was requested."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    import tui
    import tui.hot_reload as hr

    order = []

    class FakeApp:
        def __init__(self, *args, reload_requested, **kwargs):
            self._reload_requested = reload_requested

        def run(self):
            order.append("run")

    monkeypatch.setattr(tui, "set_app", lambda app: None)
    monkeypatch.setattr(hr, "do_reload", lambda: order.append("reload"))

    # Reload requested → exec happens, and strictly after run().
    monkeypatch.setattr(tui, "AgentApp", lambda *a, **k: FakeApp(reload_requested=True))
    tui.run("task", hot_reload=True)
    assert order == ["run", "reload"]

    # No reload requested → no exec.
    order.clear()
    monkeypatch.setattr(tui, "AgentApp", lambda *a, **k: FakeApp(reload_requested=False))
    tui.run("task")
    assert order == ["run"]
