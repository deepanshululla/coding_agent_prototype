"""Provider-side lifting of image tool-results.

`read_file` (raw/both mode) returns an image as a JSON payload in a role:"tool"
message. A tool result is text-only on the wire, so the provider lifts that
payload into a viewable `image_url` block on a following `user` message — this is
how a vision-capable MODEL gets to see the whole image. A caption attached by
read_file (both mode) becomes the tool-result text.
"""

import base64
import json

import pytest

import provider

_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake-image-bytes").decode("ascii")


def _img_tool_msg(tool_call_id="t1", fmt="png", caption=None):
    payload = {"type": "image", "format": fmt, "data": _B64}
    if caption is not None:
        payload["caption"] = caption
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": json.dumps(payload, separators=(",", ":")),
    }


def test_parse_image_payload_returns_caption():
    parsed = provider._parse_image_payload(_img_tool_msg(caption="a red square")["content"])
    assert parsed == ("png", _B64, "a red square")
    # No caption key → caption is None.
    no_caption = provider._parse_image_payload(_img_tool_msg()["content"])
    assert no_caption is not None and no_caption[2] is None
    # Plain text is not an image payload.
    assert provider._parse_image_payload("just text") is None


def test_lift_raw_image_uses_placeholder_and_attaches_image():
    lifted = provider._lift_tool_image_results([_img_tool_msg()])

    tool_msgs = [m for m in lifted if m["role"] == "tool"]
    user_msgs = [m for m in lifted if m["role"] == "user"]
    assert len(tool_msgs) == 1 and len(user_msgs) == 1
    # Base64 leaves the tool message (the original bug); placeholder remains.
    assert _B64 not in tool_msgs[0]["content"]
    assert "[image read" in tool_msgs[0]["content"]
    # Image is viewable on the user message.
    url = [b for b in user_msgs[0]["content"] if b.get("type") == "image_url"][0]["image_url"][
        "url"
    ]
    assert url == f"data:image/png;base64,{_B64}"


def test_lift_both_mode_caption_becomes_tool_text_and_image_attached():
    lifted = provider._lift_tool_image_results([_img_tool_msg(caption="a red square")])

    tool_msg = [m for m in lifted if m["role"] == "tool"][0]
    user_msg = [m for m in lifted if m["role"] == "user"][0]
    # The caption is the tool result text — and the image is still delivered.
    assert tool_msg["content"] == "a red square"
    assert _B64 not in tool_msg["content"]
    assert any(b.get("type") == "image_url" for b in user_msg["content"])


def test_lift_leaves_text_tool_results_untouched():
    messages = [{"role": "tool", "tool_call_id": "t1", "content": "line1\nline2"}]
    assert provider._lift_tool_image_results(messages) == messages


def test_lift_groups_multiple_images_after_the_batch():
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "t1"}, {"id": "t2"}]},
        _img_tool_msg("t1"),
        _img_tool_msg("t2"),
    ]
    lifted = provider._lift_tool_image_results(messages)
    assert [m["role"] for m in lifted] == ["assistant", "tool", "tool", "user"]
    assert len([b for b in lifted[-1]["content"] if b.get("type") == "image_url"]) == 2


def test_lift_does_not_mutate_input():
    messages = [_img_tool_msg(caption="cap")]
    original = json.dumps(messages)
    provider._lift_tool_image_results(messages)
    assert json.dumps(messages) == original


async def _fake_stream():
    yield provider._chunk(content="ok", finish_reason="stop")


@pytest.mark.asyncio
async def test_stream_response_sends_lifted_image_to_model(monkeypatch):
    """End-to-end: a tool image payload reaches litellm as a viewable image_url
    block on a user message — i.e. the model actually sees the whole image."""
    monkeypatch.setattr(provider, "USE_CLAUDE_CLI", False)
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _fake_stream()

    monkeypatch.setattr(provider.litellm, "acompletion", fake_acompletion)

    async for _ in provider.stream_response([_img_tool_msg()], "sp"):
        pass

    sent = captured["messages"]
    image_blocks = [
        b
        for m in sent
        if isinstance(m.get("content"), list)
        for b in m["content"]
        if b.get("type") == "image_url"
    ]
    assert len(image_blocks) == 1
    assert image_blocks[0]["image_url"]["url"] == f"data:image/png;base64,{_B64}"
