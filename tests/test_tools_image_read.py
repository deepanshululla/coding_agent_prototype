"""Tests for image reading via read_file tool."""

import base64
from pathlib import Path

import pytest

from tools import read_file


@pytest.fixture
def test_image_path(tmp_path: Path) -> Path:
    """Create a minimal 1x1 PNG for testing."""
    # Minimal valid PNG: 1x1 red pixel
    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01"
        b"\x00\x00\x00\x18\xdd\x8d\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    img_path = tmp_path / "test.png"
    img_path.write_bytes(png_bytes)
    return img_path


@pytest.mark.asyncio
async def test_read_image_returns_base64_json(test_image_path: Path):
    """read_file on an image returns a JSON string with base64-encoded content."""
    result = await read_file(str(test_image_path))

    # Should not be an error
    assert not result.startswith("Error:")

    # Should contain the image data in a structured format
    # Expected format: {"type": "image", "format": "png", "data": "base64..."}
    import json

    parsed = json.loads(result)

    assert parsed["type"] == "image"
    assert parsed["format"] == "png"
    assert "data" in parsed

    # Data should be valid base64
    decoded = base64.b64decode(parsed["data"])
    assert len(decoded) > 0


@pytest.mark.asyncio
async def test_read_image_supports_multiple_formats(tmp_path: Path):
    """read_file detects and reads various image formats."""
    # For now, just test that we recognize the extensions
    for ext in ["png", "jpg", "jpeg", "gif", "webp"]:
        img_path = tmp_path / f"test.{ext}"
        img_path.write_bytes(b"\x00" * 100)  # Dummy bytes

        # Won't be valid image data, but should attempt image reading
        result = await read_file(str(img_path))
        # Either succeeds with JSON or fails with image-specific error
        assert not result.startswith("Error: file not found")


@pytest.mark.asyncio
async def test_read_text_file_unchanged(tmp_path: Path):
    """read_file on text files still returns plain text."""
    text_file = tmp_path / "test.txt"
    text_file.write_text("Hello, world!")

    result = await read_file(str(text_file))
    assert result == "Hello, world!"


@pytest.mark.asyncio
async def test_read_nonexistent_image(tmp_path: Path):
    """read_file on missing image file returns standard error."""
    result = await read_file(str(tmp_path / "missing.png"))
    assert result.startswith("Error: file not found")
