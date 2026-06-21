"""VLM routing + image tool-result lifting (provider layer).

Two coupled behaviours, both in src/provider.py:

1. *Lifting* — when `read_file` reads an image it returns a JSON string
   ``{"type":"image","format":"png","data":"<base64>"}`` that the agent loop
   stores in a ``role:"tool"`` message. A tool result is plain text to every
   provider, so that base64 is invisible to the model. The provider must lift it
   into a real multimodal ``image_url`` block on a following ``user`` message.

2. *Routing* — when a turn carries an image and AGENT_VLM_MODEL is set, the
   completion is routed to that vision model (mirrors CODE_MODEL role routing).
"""

import base64
import json

import pytest

import provider

# A tiny base64 payload — the lift/route logic never decodes it, so any
# well-formed base64 stands in for a real image.
_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake-image-bytes").decode("ascii")


def _image_tool_msg(tool_call_id: str = "t1", fmt: str = "png") -> dict:
    """A role:"tool" message shaped exactly as read_file produces for an image."""
    content = json.dumps({"type": "image", "format": fmt, "data": _B64}, separators=(",", ":"))
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


# ── Lifting ───────────────────────────────────────────────────────────────────


def test_lift_replaces_image_tool_result_with_placeholder_and_user_image():
    """The base64 leaves the tool message and arrives as an image_url user block.

    The tool message keeps a short text placeholder (tool results must be text),
    and a following user message carries the image as a data URL the model can see.
    """
    messages = [_image_tool_msg()]

    lifted = provider._lift_tool_image_results(messages)

    tool_msgs = [m for m in lifted if m["role"] == "tool"]
    user_msgs = [m for m in lifted if m["role"] == "user"]
    assert len(tool_msgs) == 1
    assert len(user_msgs) == 1

    # The base64 must NOT remain in the tool message (that was the bug).
    assert _B64 not in tool_msgs[0]["content"]
    assert isinstance(tool_msgs[0]["content"], str)

    # The image rides on the user message as a proper data URL block.
    blocks = user_msgs[0]["content"]
    image_blocks = [b for b in blocks if b.get("type") == "image_url"]
    assert len(image_blocks) == 1
    url = image_blocks[0]["image_url"]["url"]
    assert url == f"data:image/png;base64,{_B64}"


def test_lift_leaves_text_tool_results_untouched():
    """A normal (text) tool result is passed through with no extra user message."""
    messages = [{"role": "tool", "tool_call_id": "t1", "content": "line1\nline2"}]

    lifted = provider._lift_tool_image_results(messages)

    assert lifted == messages  # unchanged, no image user message injected


def test_lift_groups_multiple_images_after_the_tool_batch():
    """Two image tool results in one batch produce two placeholders, then one
    user message holding both images — so the tool_result grouping providers
    require (all results before the next user turn) is preserved."""
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "t1"}, {"id": "t2"}]},
        _image_tool_msg("t1"),
        _image_tool_msg("t2"),
    ]

    lifted = provider._lift_tool_image_results(messages)

    roles = [m["role"] for m in lifted]
    # assistant, tool, tool, user(images) — the two tool messages stay adjacent.
    assert roles == ["assistant", "tool", "tool", "user"]
    image_blocks = [b for b in lifted[-1]["content"] if b.get("type") == "image_url"]
    assert len(image_blocks) == 2


def test_lift_does_not_mutate_input():
    """Lifting is non-mutating — the caller's message list is the source of truth."""
    messages = [_image_tool_msg()]
    original = json.dumps(messages)

    provider._lift_tool_image_results(messages)

    assert json.dumps(messages) == original


def test_contains_image_detects_multimodal_user_content():
    """_contains_image is True for a user message carrying an image_url block,
    and False for plain-text-only conversations."""
    with_image = [
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:..."}}]}
    ]
    text_only = [{"role": "user", "content": "hello"}]

    assert provider._contains_image(with_image) is True
    assert provider._contains_image(text_only) is False


# ── Routing ────────────────────────────────────────────────────────────────────


async def _fake_stream():
    yield provider._chunk(content="ok", finish_reason="stop")


@pytest.mark.asyncio
async def test_image_turn_routes_to_vlm_model(monkeypatch):
    """With AGENT_VLM_MODEL set and an image in the turn, the completion is routed
    to the VLM model rather than the default MODEL."""
    monkeypatch.setattr(provider, "USE_CLAUDE_CLI", False)
    monkeypatch.setattr(provider, "VLM_MODEL", "ollama/qwen3-vl:30b")
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _fake_stream()

    monkeypatch.setattr(provider.litellm, "acompletion", fake_acompletion)

    async for _ in provider.stream_response([_image_tool_msg()], "sp"):
        pass

    assert captured["model"] == "ollama/qwen3-vl:30b"


@pytest.mark.asyncio
async def test_text_turn_does_not_route_to_vlm(monkeypatch):
    """No image in the turn → VLM is not used even when configured."""
    monkeypatch.setattr(provider, "USE_CLAUDE_CLI", False)
    monkeypatch.setattr(provider, "VLM_MODEL", "ollama/qwen3-vl:30b")
    monkeypatch.setattr(provider, "MODEL", "claude-sonnet-4-5")
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _fake_stream()

    monkeypatch.setattr(provider.litellm, "acompletion", fake_acompletion)

    async for _ in provider.stream_response([{"role": "user", "content": "hi"}], "sp"):
        pass

    assert captured["model"] == "claude-sonnet-4-5"


@pytest.mark.asyncio
async def test_no_vlm_configured_keeps_main_model_on_image_turn(monkeypatch):
    """When AGENT_VLM_MODEL is empty, an image turn still goes to the main model —
    routing is opt-in, so the default single-model behaviour is unchanged."""
    monkeypatch.setattr(provider, "USE_CLAUDE_CLI", False)
    monkeypatch.setattr(provider, "VLM_MODEL", "")
    monkeypatch.setattr(provider, "MODEL", "claude-sonnet-4-5")
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _fake_stream()

    monkeypatch.setattr(provider.litellm, "acompletion", fake_acompletion)

    async for _ in provider.stream_response([_image_tool_msg()], "sp"):
        pass

    assert captured["model"] == "claude-sonnet-4-5"
