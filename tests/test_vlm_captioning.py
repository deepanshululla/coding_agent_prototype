"""read_file image delivery modes (AGENT_IMAGE_MODE) + the describe_image helper.

  raw     → base64 image payload (provider lifts it so MODEL sees the image)
  caption → VLM description text only (for a non-vision driver)
  both    → image payload carrying the caption too (default)

"caption"/"both" call the VLM with NO tools (it only sees). Without AGENT_VLM_MODEL
they degrade to raw. Mirrors the CODE_MODEL / write_code sub-model pattern.
"""

import base64
import json
from types import SimpleNamespace

import pytest

import config
import provider
import tools

_RAW = b"\x89PNGfake-bytes"


def _png(tmp_path):
    img = tmp_path / "shot.png"
    img.write_bytes(_RAW)
    return img


def _fake_response(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


# ── describe_image ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_describe_image_passes_image_and_no_tools(monkeypatch):
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _fake_response("a solid red square")

    monkeypatch.setattr(provider.litellm, "acompletion", fake_acompletion)

    out = await provider.describe_image(_RAW, "png", "ollama/qwen3-vl:30b")

    assert out == "a solid red square"
    assert captured["model"] == "ollama/qwen3-vl:30b"
    assert "tools" not in captured and "tool_choice" not in captured
    blocks = captured["messages"][0]["content"]
    assert [b for b in blocks if b.get("type") == "image_url"][0]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )


# ── read_file modes ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_both_mode_default_emits_image_with_caption(monkeypatch, tmp_path):
    """Default (both) + VLM: payload carries both the raw image and the caption."""
    monkeypatch.setattr(config, "IMAGE_MODE", "both")
    monkeypatch.setattr(config, "VLM_MODEL", "ollama/qwen3-vl:30b")

    async def fake_describe(image_bytes, fmt, model):
        return "a login screen with a red error banner"

    monkeypatch.setattr(provider, "describe_image", fake_describe)

    payload = json.loads(await tools.read_file(str(_png(tmp_path))))
    assert payload["type"] == "image"
    assert payload["data"] == base64.b64encode(_RAW).decode("ascii")  # whole image present
    assert "red error banner" in payload["caption"]  # caption rides along


@pytest.mark.asyncio
async def test_both_mode_without_vlm_degrades_to_raw(monkeypatch, tmp_path):
    """both is the default, but with no VLM there is nothing to caption with, so it
    falls back to a raw image payload (no caption key)."""
    monkeypatch.setattr(config, "IMAGE_MODE", "both")
    monkeypatch.setattr(config, "VLM_MODEL", "")

    payload = json.loads(await tools.read_file(str(_png(tmp_path))))
    assert payload["type"] == "image"
    assert payload["data"] == base64.b64encode(_RAW).decode("ascii")
    assert "caption" not in payload


@pytest.mark.asyncio
async def test_caption_mode_returns_text_only(monkeypatch, tmp_path):
    """caption mode hands back just the description — no pixels for a non-vision driver."""
    monkeypatch.setattr(config, "IMAGE_MODE", "caption")
    monkeypatch.setattr(config, "VLM_MODEL", "ollama/qwen3-vl:30b")

    async def fake_describe(image_bytes, fmt, model):
        return "a bar chart trending upward"

    monkeypatch.setattr(provider, "describe_image", fake_describe)

    result = await tools.read_file(str(_png(tmp_path)))
    assert "bar chart trending upward" in result
    assert '"type":"image"' not in result  # no base64 payload
    assert base64.b64encode(_RAW).decode() not in result


@pytest.mark.asyncio
async def test_raw_mode_never_calls_vlm(monkeypatch, tmp_path):
    """raw mode returns the image payload and must not invoke the VLM at all,
    even when one is configured."""
    monkeypatch.setattr(config, "IMAGE_MODE", "raw")
    monkeypatch.setattr(config, "VLM_MODEL", "ollama/qwen3-vl:30b")

    async def boom(*a, **k):
        raise AssertionError("describe_image must not be called in raw mode")

    monkeypatch.setattr(provider, "describe_image", boom)

    payload = json.loads(await tools.read_file(str(_png(tmp_path))))
    assert payload["data"] == base64.b64encode(_RAW).decode("ascii")
    assert "caption" not in payload


@pytest.mark.asyncio
async def test_vlm_error_surfaces_as_tool_error(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "IMAGE_MODE", "both")
    monkeypatch.setattr(config, "VLM_MODEL", "ollama/qwen3-vl:30b")

    async def boom(image_bytes, fmt, model):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(provider, "describe_image", boom)

    result = await tools.read_file(str(_png(tmp_path)))
    assert "Error describing image" in result and "connection refused" in result


@pytest.mark.asyncio
async def test_read_file_text_unaffected(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("line1\nline2\nline3")
    assert await tools.read_file(str(f)) == "line1\nline2\nline3"
