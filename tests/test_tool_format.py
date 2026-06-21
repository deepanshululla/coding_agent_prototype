"""Tests for tui.tool_format — turning a tool call (name + input) into the
human-readable summary / detail / short-label the TUI shows.

Covers both naming conventions: the `claude -p` fork's CamelCase tools (Read,
Edit, Bash, Write, Grep, Glob) and this project's own snake_case tools
(read_file, edit_file, bash, …), plus the file_path vs path key difference.
"""

from tui.tool_format import format_tool_call


def test_read_shows_file_path():
    d = format_tool_call("Read", {"file_path": "src/architecture.py"})
    assert d.summary == "Reading file"
    assert d.detail == "src/architecture.py"
    assert d.short == "architecture.py"
    assert d.expandable is True


def test_read_native_uses_path_key():
    d = format_tool_call("read_file", {"path": "src/agent.py"})
    assert d.summary == "Reading file"
    assert d.detail == "src/agent.py"


def test_bash_shows_command():
    d = format_tool_call("Bash", {"command": "git push"})
    assert d.summary == "Running command"
    assert d.detail == "git push"
    assert d.short == "git push"
    assert d.expandable is False


def test_edit_shows_change_counts():
    d = format_tool_call(
        "Edit",
        {
            "file_path": "src/provider.py",
            "old_string": "a\nb\nc",  # 3 lines removed
            "new_string": "a\nb\nc\nd\ne",  # 5 lines added
        },
    )
    assert d.summary == "Edited src/provider.py (+5 −3)"
    assert d.detail is None
    assert d.expandable is True


def test_edit_native_name_and_path_key():
    d = format_tool_call(
        "edit_file",
        {"path": "x.py", "old_string": "one", "new_string": "one\ntwo"},
    )
    assert d.summary == "Edited x.py (+2 −1)"


def test_write_shows_added_line_count():
    d = format_tool_call("Write", {"file_path": "new.py", "content": "line1\nline2\nline3"})
    assert d.summary == "Wrote new.py (+3)"


def test_grep_and_glob_show_pattern():
    g = format_tool_call("Grep", {"pattern": "TODO"})
    assert g.summary == "Searching"
    assert g.detail == "TODO"

    glob = format_tool_call("find_files", {"pattern": "*.py"})
    assert glob.summary == "Finding files"
    assert glob.detail == "*.py"


def test_unknown_tool_falls_back_to_name():
    d = format_tool_call("mystery_tool", {"foo": "bar"})
    assert d.summary == "mystery_tool"
    assert d.expandable is False


def test_long_command_short_label_is_truncated():
    cmd = "git log --oneline --graph --decorate --all --since='2 weeks ago'"
    d = format_tool_call("Bash", {"command": cmd})
    assert len(d.short) <= 24
    assert d.short.endswith("…")
