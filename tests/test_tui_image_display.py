# tests/test_tui_image_display.py

"""Test that the TUI can display images inline in the transcript."""

import base64

from tui.components.transcript import TranscriptPane


def test_append_user_message_with_image():
    """append_user_message should handle multimodal content without crashing."""
    pane = TranscriptPane()

    # Create a tiny 1x1 red PNG
    red_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="
    )
    data_url = f"data:image/png;base64,{base64.b64encode(red_png).decode('ascii')}"

    # Multimodal content with text and image
    content = [
        {"type": "text", "text": "Here's a screenshot"},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]

    # Should not crash when displaying multimodal content
    pane.append_user_message(content)
    assert True


def test_append_user_message_plain_text():
    """append_user_message should work with plain text (backward compat)."""
    pane = TranscriptPane()

    # Should handle plain string content
    pane.append_user_message("Just plain text")
    assert True


def test_append_user_message_multiple_images():
    """append_user_message should handle multiple images in one message."""
    pane = TranscriptPane()

    red_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="
    )
    data_url = f"data:image/png;base64,{base64.b64encode(red_png).decode('ascii')}"

    content = [
        {"type": "text", "text": "Two images:"},
        {"type": "image_url", "image_url": {"url": data_url}},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]

    # Should handle multiple images without crashing
    pane.append_user_message(content)
    assert True


def test_parse_image_url():
    """_parse_image_url should extract format and size from data URL."""
    pane = TranscriptPane()

    # Test PNG data URL
    red_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="
    )
    data_url = f"data:image/png;base64,{base64.b64encode(red_png).decode('ascii')}"

    info = pane._parse_image_url(data_url)

    assert info["format"] == "PNG"
    # Should parse size in bytes
    assert "B" in info["size"]


def test_parse_image_url_jpeg():
    """_parse_image_url should handle JPEG format."""
    pane = TranscriptPane()

    # Minimal JPEG data
    jpeg_data = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
    data_url = f"data:image/jpeg;base64,{base64.b64encode(jpeg_data).decode('ascii')}"

    info = pane._parse_image_url(data_url)

    assert info["format"] == "JPEG"
    assert len(jpeg_data) == 22  # Verify actual size
    assert info["size"] == "22 B"


def test_parse_image_url_invalid():
    """_parse_image_url should handle invalid URLs gracefully."""
    pane = TranscriptPane()

    info = pane._parse_image_url("not-a-data-url")

    assert info["format"] == "unknown"
    assert info["size"] == "unknown size"
