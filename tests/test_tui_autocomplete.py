# tests/test_tui_autocomplete.py

"""Tests for TUI slash command autocomplete."""

from tui.commands import get_command_names
from tui.components.input_box import InputBox


def test_get_command_names():
    """get_command_names returns sorted list of registered commands."""
    names = get_command_names()
    assert isinstance(names, list)
    assert len(names) > 0
    assert "help" in names
    assert "model" in names
    assert "usage" in names
    assert "skill" in names
    assert names == sorted(names)


def test_get_completions_all_commands():
    """_get_completions with '/' returns all commands."""
    input_box = InputBox()
    completions = input_box._get_completions("/")
    commands = get_command_names()
    assert completions == commands


def test_get_completions_prefix_match():
    """_get_completions filters by prefix."""
    input_box = InputBox()
    completions = input_box._get_completions("/mo")
    assert "model" in completions
    # Should only return commands starting with "mo"
    for cmd in completions:
        assert cmd.startswith("mo")


def test_get_completions_no_match():
    """_get_completions returns empty list when no matches."""
    input_box = InputBox()
    completions = input_box._get_completions("/xyz")
    assert completions == []


def test_get_completions_non_slash():
    """_get_completions returns empty for non-slash input."""
    input_box = InputBox()
    completions = input_box._get_completions("hello")
    assert completions == []


def test_completion_state_initialization():
    """InputBox initializes with empty completion state."""
    input_box = InputBox()
    assert input_box._completion_candidates == []
    assert input_box._completion_index == -1
    assert input_box._completion_prefix == ""


def test_reset_completion():
    """_reset_completion clears all state."""
    input_box = InputBox()
    # Set some state
    input_box._completion_candidates = ["help", "model"]
    input_box._completion_index = 1
    input_box._completion_prefix = "/h"

    # Reset
    input_box._reset_completion()

    assert input_box._completion_candidates == []
    assert input_box._completion_index == -1
    assert input_box._completion_prefix == ""
