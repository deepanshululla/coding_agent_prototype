"""Integration test demonstrating image reading works end-to-end."""

import json
from pathlib import Path

import pytest

from tools import TOOL_REGISTRY


@pytest.fixture
def minimal_png(tmp_path: Path) -> Path:
    """Create a minimal 1x1 PNG for testing."""
    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01"
        b"\x00\x00\x00\x18\xdd\x8d\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    img_path = tmp_path / "screenshot.png"
    img_path.write_bytes(png_bytes)
    return img_path


@pytest.mark.asyncio
async def test_read_file_tool_returns_base64_for_images(minimal_png: Path):
    """The read_file tool returns base64 JSON for image files."""
    read_file = TOOL_REGISTRY["read_file"]

    result = await read_file(path=str(minimal_png))

    # Should be JSON with image data
    parsed = json.loads(result)
    assert parsed["type"] == "image"
    assert parsed["format"] == "png"
    assert len(parsed["data"]) > 0


@pytest.mark.asyncio
async def test_read_file_tool_returns_text_for_text_files(tmp_path: Path):
    """The read_file tool returns plain text for non-image files."""
    text_file = tmp_path / "readme.txt"
    text_file.write_text("Hello, world!")

    read_file = TOOL_REGISTRY["read_file"]
    result = await read_file(path=str(text_file))

    # Should be plain text
    assert result == "Hello, world!"
    # Should NOT be JSON
    with pytest.raises(json.JSONDecodeError):
        json.loads(result)


@pytest.mark.asyncio
async def test_different_image_formats(tmp_path: Path):
    """read_file correctly identifies format from extension."""
    read_file = TOOL_REGISTRY["read_file"]

    for ext, expected_format in [("png", "png"), ("jpg", "jpg"), ("jpeg", "jpeg")]:
        img_file = tmp_path / f"test.{ext}"
        img_file.write_bytes(b"\x00" * 100)

        result = await read_file(path=str(img_file))
        parsed = json.loads(result)

        assert parsed["format"] == expected_format
