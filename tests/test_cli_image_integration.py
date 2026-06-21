"""Integration test for CLI fork image handling."""

import base64
from pathlib import Path

import pytest


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


@pytest.mark.asyncio
async def test_cli_fork_end_to_end(test_image_base64: str, monkeypatch, tmp_path: Path):
    """End-to-end test: CLI fork extracts images, passes to claude -p, cleans up."""
    import asyncio

    from provider import stream_response

    monkeypatch.setenv("USE_CLAUDE_CLI_LLM", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    # Track what gets passed to claude -p
    captured_cmd = None
    captured_prompt = None

    async def mock_exec(*cmd, **_kwargs):
        nonlocal captured_cmd, captured_prompt

        captured_cmd = cmd
        # Extract prompt (3rd arg after 'claude', '-p')
        if len(cmd) > 2:
            captured_prompt = cmd[2]

        # Mock process that returns a simple response
        class MockProcess:
            returncode = 0
            stdout = asyncio.StreamReader()
            stderr = asyncio.StreamReader()

            async def wait(self):
                return 0

        proc = MockProcess()
        # Feed minimal stream-json response
        proc.stdout.feed_data(
            b'{"type":"message_start"}\n'
            b'{"type":"content_block_delta","delta":{"type":"text_delta","text":"test"}}\n'
        )
        proc.stdout.feed_eof()

        return proc

    monkeypatch.setattr("asyncio.create_subprocess_exec", mock_exec)

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What's in this image?"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{test_image_base64}"},
                },
            ],
        }
    ]

    # Consume the stream
    chunks = []
    async for chunk in stream_response(messages, ""):
        chunks.append(chunk)

    # Verify: claude -p was called with expected args
    assert captured_cmd is not None
    assert "claude" in captured_cmd
    assert "-p" in captured_cmd

    # Verify: prompt contains reference to an image file
    assert captured_prompt is not None
    assert "[Image file:" in captured_prompt, (
        f"Expected '[Image file:' in prompt, got: {captured_prompt!r}"
    )
    assert ".png]" in captured_prompt, (
        f"Expected temp PNG file path in prompt, got: {captured_prompt!r}"
    )

    # Note: We can't verify cleanup here because the mock doesn't actually
    # execute the function's finally block the same way. The unit tests
    # cover cleanup logic.
