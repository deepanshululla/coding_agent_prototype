# tests/test_transcript_selection.py

"""Tests for transcript text selection and copying functionality."""

from unittest.mock import patch

import pytest

from tui.app import AgentApp
from tui.components.transcript import TranscriptPane


@pytest.mark.asyncio
async def test_transcript_allows_text_selection():
    """Transcript should enable text selection by default."""
    async with AgentApp("").run_test() as pilot:
        app = pilot.app
        transcript = app.query_one(TranscriptPane)
        assert transcript.allow_select is True


@pytest.mark.asyncio
async def test_copy_action_when_transcript_focused():
    """When transcript is focused with text selected, action_copy should copy to clipboard."""
    async with AgentApp("").run_test() as pilot:
        app = pilot.app
        transcript = app.query_one(TranscriptPane)

        # Add text to transcript
        transcript.append_text("Line 1\nLine 2\nLine 3")

        # Focus the transcript
        transcript.focus()

        # Pause to let the app update
        await pilot.pause()

        # Select all text first
        transcript.text_select_all()

        # Pause to let selection update
        await pilot.pause()

        # Mock clipboard and selected text to verify copy logic
        with patch.object(app, "copy_to_clipboard") as mock_copy:
            # Mock screen.get_selected_text to return something
            with patch.object(
                transcript.screen, "get_selected_text", return_value="Line 1\nLine 2\nLine 3"
            ):
                # Call the copy action
                transcript.action_copy()
                # Should have called clipboard with selected text
                assert mock_copy.called, "copy_to_clipboard should be called"
                mock_copy.assert_called_once_with("Line 1\nLine 2\nLine 3")


@pytest.mark.asyncio
async def test_transcript_has_can_focus():
    """Transcript should be focusable to receive keyboard events for selection."""
    async with AgentApp("").run_test() as pilot:
        app = pilot.app
        transcript = app.query_one(TranscriptPane)

        # Transcript should be able to receive focus
        assert transcript.can_focus is True

        # Should be able to focus it
        transcript.focus()
        assert app.focused == transcript
