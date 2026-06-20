"""Initial-task resolution: the TUI starts idle (no stdin prompt); stdout still
prompts when no task is given on the command line.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import main  # noqa: E402


def test_initial_task_tui_no_args_is_empty():
    # The TUI must NOT block on input(); it launches idle and waits for the
    # first steering message typed into the input box.
    assert main._initial_task([], "tui") == ""


def test_initial_task_tui_with_args_joins_them():
    assert main._initial_task(["fix", "the", "bug"], "tui") == "fix the bug"


def test_initial_task_stdout_with_args_joins_them():
    assert main._initial_task(["summarize", "repo"], "stdout") == "summarize repo"


def test_initial_task_stdout_no_args_prompts(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "typed task")
    assert main._initial_task([], "stdout") == "typed task"
