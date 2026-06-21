"""Tests for Claude CLI fork image handling."""

import base64
from pathlib import Path

import pytest

from provider import _flatten_content, _save_images_to_temp


@pytest.fixture
def test_image_base64() -> str:
    """Minimal 1x1 PNG as base64."""
    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01"
        b"\x00\x00\x00\x18\xdd\x8d\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return base64.b64encode(png_bytes).decode("utf-8")


def test_save_images_to_temp_creates_files(test_image_base64: str, tmp_path: Path):
    """_save_images_to_temp extracts images and saves them to temp files."""
    content = [
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{test_image_base64}"}},
    ]

    result, temp_files = _save_images_to_temp(content, tmp_path)

    # Should have created 1 temp file
    assert len(temp_files) == 1
    temp_file = temp_files[0]

    # Temp file should exist and contain the PNG data
    assert temp_file.exists()
    data = temp_file.read_bytes()
    assert data.startswith(b"\x89PNG"), "Temp file doesn't contain valid PNG data"

    # Result should replace image_url with a text reference
    assert len(result) == 2
    assert result[0]["type"] == "text"
    assert result[1]["type"] == "text"
    assert str(temp_file) in result[1]["text"]


def test_save_images_handles_multiple_images(test_image_base64: str, tmp_path: Path):
    """_save_images_to_temp handles multiple images in one message."""
    content = [
        {"type": "text", "text": "Compare these:"},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{test_image_base64}"}},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{test_image_base64}"}},
    ]

    result, temp_files = _save_images_to_temp(content, tmp_path)

    # Should create 2 temp files
    assert len(temp_files) == 2

    # Both should exist and contain PNG data
    for temp_file in temp_files:
        assert temp_file.exists()
        assert temp_file.read_bytes().startswith(b"\x89PNG")

    # Result should have 3 text blocks (original text + 2 image references)
    assert len(result) == 3
    assert all(block["type"] == "text" for block in result)


def test_save_images_preserves_text_only_content(tmp_path: Path):
    """_save_images_to_temp leaves text-only content unchanged."""
    content = [{"type": "text", "text": "Just plain text"}]

    result, temp_files = _save_images_to_temp(content, tmp_path)

    # No temp files should be created
    assert len(temp_files) == 0

    # Content should be unchanged
    assert result == content


def test_flatten_content_strips_images(test_image_base64: str):
    """_flatten_content strips images for text-only claude -p mode."""
    content = [
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{test_image_base64}"}},
    ]

    result = _flatten_content(content)

    # Should strip the image and show placeholder
    assert "What's in this image?" in result
    assert "[image omitted" in result or "image" not in result.lower()
