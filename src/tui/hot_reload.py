"""Hot reload infrastructure for the TUI.

Handles state serialization/restoration and file watching for automatic reload
when source files change during development.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tui.app import AgentApp

# State files older than this are ignored (avoids loading stale state from crashes)
MAX_STATE_AGE_SECONDS = 3600  # 1 hour


def save_tui_state(app: AgentApp) -> Path:
    """Serialize TUI state to /tmp for restoration after reload.

    Returns the path to the saved state file (keyed by PID to avoid collisions).
    """
    from tui.components.transcript import TranscriptPane

    state_file = Path(f"/tmp/tui-hot-reload-state-{os.getpid()}.json")

    # Extract transcript text
    transcript = app.query_one(TranscriptPane)
    transcript_text = transcript.get_text()

    state = {
        "task": app._agent_task,
        "transcript": transcript_text,
        "timestamp": time.time(),
    }

    state_file.write_text(json.dumps(state, indent=2))
    return state_file


def load_tui_state() -> dict | None:
    """Load previously saved TUI state from /tmp.

    Returns None if no state file exists or if it's too old (stale from a crash).
    """
    state_file = Path(f"/tmp/tui-hot-reload-state-{os.getpid()}.json")
    if not state_file.exists():
        return None

    try:
        state = json.loads(state_file.read_text())
        # Ignore stale state from old crashes
        if time.time() - state.get("timestamp", 0) > MAX_STATE_AGE_SECONDS:
            return None
        return state
    except (json.JSONDecodeError, OSError):
        return None


async def watch_tui_files(app: AgentApp) -> None:
    """Watch src/tui/**/*.py for changes and trigger reload.

    Debounces changes with a 200ms window to handle bulk saves.
    Runs forever until the app shuts down.
    """
    from watchfiles import awatch

    src_tui = Path(__file__).parent  # src/tui directory

    async for changes in awatch(src_tui, debounce=200):
        # Filter to .py files only (ignore __pycache__, .pyc, etc.)
        py_changes = [c for c in changes if c[1].endswith(".py")]
        if py_changes:
            app.trigger_reload()
            break  # Exit after triggering reload (process will restart)


def do_reload() -> None:
    """Restart the current process with the same arguments.

    Uses os.execv to replace the current process (no subprocess overhead).
    """
    os.execv(sys.executable, [sys.executable] + sys.argv)
