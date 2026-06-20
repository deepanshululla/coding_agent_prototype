"""BDD gate for Ctrl+V image paste in the TUI.

A terminal never sends image bytes on Ctrl+V, so the key is only a trigger that
reads the OS clipboard (tui.clipboard, mocked here). These tests drive AgentApp
through Textual's Pilot and assert:

  - pasting a clipboard image buffers one image_url content block,
  - submitting with a pending image builds multimodal list content and clears
    the buffer,
  - submitting with no image keeps the plain-string content (no regression),
  - an oversized clipboard image is rejected with a hint and never buffered,
  - an empty clipboard sets a hint and buffers nothing.
"""

import asyncio

import config
from tui import clipboard
from tui.app import AgentApp
from tui.components.input_box import InputBox
from tui.components.status_bar import StatusBar


def _status_plain(bar: StatusBar) -> str:
    from rich.text import Text

    content = bar.render()  # Static.render() returns the current renderable
    return content.plain if isinstance(content, Text) else str(content)


def test_paste_buffers_image_block(monkeypatch):
    monkeypatch.setattr(clipboard, "read_clipboard_image", lambda: (b"\x89PNGdata", "image/png"))

    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            app.action_paste_image()
            await pilot.pause()
            assert len(app._pending_images) == 1
            block = app._pending_images[0]
            assert block["type"] == "image_url"
            assert block["image_url"]["url"].startswith("data:image/png;base64,")

    asyncio.run(_run())


def test_submit_with_image_builds_multimodal_content(monkeypatch):
    monkeypatch.setattr(clipboard, "read_clipboard_image", lambda: (b"\x89PNGdata", "image/png"))
    pending: list[dict] = []

    async def _run():
        app = AgentApp("noop", pending)
        async with app.run_test() as pilot:
            app.action_paste_image()
            await pilot.pause()
            box = app.query_one(InputBox)
            box.focus()
            await pilot.pause()
            box.value = "what is this?"
            await pilot.press("enter")
            await pilot.pause()
            # Buffer is flushed on submit.
            assert app._pending_images == []

    asyncio.run(_run())

    assert len(pending) == 1
    content = pending[0]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "what is this?"}
    assert content[1]["type"] == "image_url"


def test_submit_without_image_stays_plain_string():
    pending: list[dict] = []

    async def _run():
        app = AgentApp("noop", pending)
        async with app.run_test() as pilot:
            box = app.query_one(InputBox)
            box.focus()
            await pilot.pause()
            box.value = "just text"
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(_run())

    assert pending == [{"role": "user", "content": "just text"}]


def test_oversized_image_rejected_with_hint(monkeypatch):
    monkeypatch.setattr(config, "IMAGE_MAX_BYTES", 4)
    monkeypatch.setattr(
        clipboard, "read_clipboard_image", lambda: (b"way-too-many-bytes", "image/png")
    )

    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            app.action_paste_image()
            await pilot.pause()
            assert app._pending_images == []
            assert "large" in _status_plain(app.query_one(StatusBar)).lower()

    asyncio.run(_run())


def test_empty_clipboard_sets_hint_buffers_nothing(monkeypatch):
    monkeypatch.setattr(clipboard, "read_clipboard_image", lambda: None)

    async def _run():
        app = AgentApp("noop")
        async with app.run_test() as pilot:
            app.action_paste_image()
            await pilot.pause()
            assert app._pending_images == []
            assert "image" in _status_plain(app.query_one(StatusBar)).lower()

    asyncio.run(_run())


def test_paste_disabled_blocks_action(monkeypatch):
    """AGENT_IMAGE_PASTE off → the ctrl+v action is gated out via check_action."""
    monkeypatch.setattr(config, "IMAGE_PASTE", False)

    async def _run():
        app = AgentApp("noop")
        async with app.run_test():
            assert app.check_action("paste_image", None) is False

    asyncio.run(_run())

    monkeypatch.setattr(config, "IMAGE_PASTE", True)

    async def _run_enabled():
        app = AgentApp("noop")
        async with app.run_test():
            assert app.check_action("paste_image", None) is True

    asyncio.run(_run_enabled())
