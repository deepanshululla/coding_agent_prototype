"""Streaming text in the transcript must keep logical lines intact.

RichLog renders every write() as its own row, so writing each streamed delta
verbatim fragments a sentence wherever a chunk boundary fell ("...features R" /
"ichLog supports..."). The pane instead accumulates the open line and re-renders
it in place, committing completed lines on real newlines — and flushing the open
line before tool-call / user echoes so ordering is preserved.
"""

import asyncio

from tui.app import AgentApp
from tui.components.transcript import TranscriptPane


def _rows(pane: TranscriptPane) -> list[str]:
    return [strip.text for strip in pane.lines]


def test_split_word_deltas_render_as_one_line():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            pane = app.query_one(TranscriptPane)
            # A word split across two deltas, then a newline closing the line.
            pane.append_text("Let me check what features R")
            pane.append_text("ichLog supports.\n")
            await pilot.pause()
            rows = _rows(pane)
            assert "Let me check what features RichLog supports." in rows
            # The fragment boundary must NOT have produced its own row.
            assert "Let me check what features R" not in rows

    asyncio.run(_run())


def test_open_line_is_committed_as_one_row_on_finalize():
    """An open line (no trailing newline) is buffered as it streams, then
    committed as a single row at turn end — never one row per delta."""

    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            pane = app.query_one(TranscriptPane)
            pane.append_text("hello ")
            pane.append_text("world")  # still open — no newline yet
            pane.finalize_turn()
            await pilot.pause()
            assert _rows(pane) == ["hello world"]

    asyncio.run(_run())


def test_tool_call_flushes_open_line_and_preserves_order():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            pane = app.query_one(TranscriptPane)
            pane.append_text("Let me read it")  # open line, no newline
            pane.append_tool_call("Read", {"file_path": "x.py"})
            pane.append_text("done")
            pane.finalize_turn()
            await pilot.pause()
            rows = _rows(pane)
            assert rows[0] == "Let me read it"  # flushed before the tool line
            assert any("Reading file" in r for r in rows)
            assert rows[-1] == "done"

    asyncio.run(_run())


def test_blank_line_between_paragraphs_is_preserved():
    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            pane = app.query_one(TranscriptPane)
            pane.append_text("para one\n\npara two\n")
            await pilot.pause()
            rows = _rows(pane)
            assert "para one" in rows
            assert "para two" in rows
            assert "" in rows  # the blank separator survives

    asyncio.run(_run())
