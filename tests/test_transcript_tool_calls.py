"""Tests for tool-call rendering in the transcript pane (the main window) and
for finalize_turn no longer wiping the log.

append_tool_call writes a Claude-Code-style summary line naming the action and
target, so the main window says which file was read, which command ran, and
which file changed. finalize_turn must NOT clear the whole log, or those lines
(and prior turns) would vanish on any markdown turn.
"""

from rich.text import Text

from tui.components.transcript import TranscriptPane


def _capture(pane: TranscriptPane) -> list[str]:
    """Replace pane.write with a recorder, returning the list it appends to."""
    written: list[str] = []

    def _rec(renderable, **kwargs):
        written.append(renderable.plain if isinstance(renderable, Text) else str(renderable))

    pane.write = _rec  # ty: ignore[invalid-assignment]
    return written


def test_append_tool_call_read_names_file_with_expand_hint():
    pane = TranscriptPane(markup=False, highlight=False)
    out = _capture(pane)
    pane.append_tool_call("Read", {"file_path": "src/architecture.py"})
    joined = "\n".join(out)
    assert "Reading file" in joined
    assert "src/architecture.py" in joined
    assert "ctrl+o to expand" in joined


def test_append_tool_call_bash_names_command_without_hint():
    pane = TranscriptPane(markup=False, highlight=False)
    out = _capture(pane)
    pane.append_tool_call("Bash", {"command": "git push"})
    joined = "\n".join(out)
    assert "Running command" in joined
    assert "git push" in joined
    assert "ctrl+o" not in joined  # commands are shown in full, nothing to expand


def test_append_tool_call_edit_shows_change_counts_no_ellipsis():
    pane = TranscriptPane(markup=False, highlight=False)
    out = _capture(pane)
    pane.append_tool_call("Edit", {"file_path": "x.py", "old_string": "a", "new_string": "a\nb\nc"})
    joined = "\n".join(out)
    assert "Edited x.py (+3 −1)" in joined
    # A completed, counted summary should not carry the in-progress ellipsis.
    assert "Edited x.py (+3 −1)…" not in joined


def test_finalize_turn_does_not_clear_the_log():
    pane = TranscriptPane(markup=False, highlight=False)
    cleared: list[int] = []
    pane.clear = lambda *a, **k: cleared.append(1)  # ty: ignore[invalid-assignment]

    pane.append_text("# Heading\n\n**bold** body")  # markdown that previously triggered clear()
    pane.finalize_turn()

    assert cleared == []  # must not wipe tool lines / prior turns
    assert pane._current_turn_buffer == ""  # buffer still resets for the next turn
