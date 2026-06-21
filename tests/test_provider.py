import inspect
import json
from types import SimpleNamespace

import pytest

import provider


def test_stream_response_is_async_generator():
    """stream_response must be an async generator function — the loop depends on it.

    The backend swapped from `claude -p` to litellm.acompletion in Phase 11, but
    the signature contract is unchanged: stream_response stays an async generator
    yielding OpenAI-format chunks, so the agent loop never changes.
    """
    assert inspect.isasyncgenfunction(provider.stream_response)


async def _fake_acompletion_stream():
    """One trivial chunk, so the async-for in stream_response has something to
    iterate without hitting a real provider."""
    yield provider._chunk(content="hi", finish_reason="stop")


@pytest.mark.asyncio
async def test_stream_response_default_model(monkeypatch):
    """With no override, stream_response routes to provider.MODEL (the default).

    Phase 13.6 adds an optional `model` param; when omitted the call must keep
    using the module-level MODEL so existing callers and mocks are unaffected.
    """
    # Pin the litellm path: importing litellm runs load_dotenv(), so a dev `.env`
    # with USE_CLAUDE_CLI_LLM=1 would otherwise flip provider to the CLI fork and
    # acompletion would never be called. This test asserts the litellm branch.
    monkeypatch.setattr(provider, "USE_CLAUDE_CLI", False)
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _fake_acompletion_stream()

    monkeypatch.setattr(provider.litellm, "acompletion", fake_acompletion)

    async for _ in provider.stream_response([{"role": "user", "content": "x"}], "sp"):
        pass

    assert captured["model"] == provider.MODEL


@pytest.mark.asyncio
async def test_stream_response_model_override(monkeypatch):
    """An explicit model= overrides provider.MODEL on the litellm call.

    BDD: Given default MODEL "claude-sonnet-4-5", When stream_response is called
    with model="gpt-4o", Then litellm.acompletion is called with model="gpt-4o".
    """
    # Pin the litellm path regardless of any ambient USE_CLAUDE_CLI_LLM (litellm's
    # import-time load_dotenv() can otherwise pull it from a dev `.env`).
    monkeypatch.setattr(provider, "USE_CLAUDE_CLI", False)
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _fake_acompletion_stream()

    monkeypatch.setattr(provider.litellm, "acompletion", fake_acompletion)

    async for _ in provider.stream_response(
        [{"role": "user", "content": "x"}], "sp", model="gpt-4o"
    ):
        pass

    assert captured["model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_use_claude_cli_skips_litellm(monkeypatch):
    """USE_CLAUDE_CLI=True routes through _claude_cli_stream, not litellm.

    BDD: Given USE_CLAUDE_CLI_LLM=1, When stream_response is called, Then
    _claude_cli_stream is called instead of litellm.acompletion.
    """
    monkeypatch.setattr(provider, "USE_CLAUDE_CLI", True)

    async def boom(**kwargs):
        raise AssertionError("litellm.acompletion must not be called in CLI mode")

    monkeypatch.setattr(provider.litellm, "acompletion", boom)

    called = {}

    async def fake_cli_stream(messages, system_prompt, model=None):
        called["hit"] = True
        yield provider._chunk(content="from-cli", finish_reason="stop")

    monkeypatch.setattr(provider, "_claude_cli_stream", fake_cli_stream)

    chunks = [c async for c in provider.stream_response([{"role": "user", "content": "x"}], "sp")]

    assert called.get("hit") is True
    assert chunks[0].choices[0].delta.content == "from-cli"


# ── stream-json line parsing (token-level streaming on the CLI path) ─────────


def _delta_line(text: str) -> bytes:
    """One stream-json content_block_delta NDJSON line carrying a text token."""
    return (
        json.dumps(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": text},
                },
            }
        )
        + "\n"
    ).encode()


# ── stream-json tool parsing (tool_use / tool_result on the CLI path) ─────────


def _tool_start_line(tool_id: str, name: str, tool_input: dict | None = None) -> bytes:
    """A complete assistant message carrying one finished tool_use block.

    Tool calls are read from the complete assistant message (not the partial
    content_block_start), so the full input is available to the UI.
    """
    return (
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": tool_id,
                            "name": name,
                            "input": tool_input or {},
                        }
                    ]
                },
            }
        )
        + "\n"
    ).encode()


def _tool_result_line(tool_id: str, content: str, is_error: bool = False) -> bytes:
    """A top-level user message carrying the subprocess's tool_result block."""
    return (
        json.dumps(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": content,
                            "is_error": is_error,
                        }
                    ]
                },
            }
        )
        + "\n"
    ).encode()


def test_parse_stream_json_line_text_descriptor():
    assert provider._parse_stream_json_line(_delta_line("Hi")) == [{"kind": "text", "text": "Hi"}]


def test_parse_stream_json_line_tool_start_descriptor():
    line = _tool_start_line("toolu_1", "Read", {"file_path": "src/agent.py"})
    assert provider._parse_stream_json_line(line) == [
        {
            "kind": "tool_start",
            "id": "toolu_1",
            "name": "Read",
            "input": {"file_path": "src/agent.py"},
        }
    ]


def test_parse_stream_json_line_tool_result_descriptor():
    assert provider._parse_stream_json_line(_tool_result_line("toolu_1", "hello world")) == [
        {"kind": "tool_end", "id": "toolu_1", "is_error": False, "chars": 11}
    ]


def test_parse_stream_json_line_tool_result_error():
    [d] = provider._parse_stream_json_line(_tool_result_line("toolu_2", "boom", is_error=True))
    assert d["kind"] == "tool_end"
    assert d["is_error"] is True


def test_parse_stream_json_line_ignores_noise():
    assert provider._parse_stream_json_line(b"not json\n") == []
    assert provider._parse_stream_json_line(b'{"type":"system","subtype":"init"}\n') == []


@pytest.mark.asyncio
async def test_claude_cli_stream_emits_tool_events(monkeypatch):
    """The subprocess runs its own tools; _claude_cli_stream surfaces them as
    tool_call_start / tool_call_end events (for the activity panel) WITHOUT
    yielding them as tool_call chunks (which would make the agent re-dispatch).
    """

    class FakeStdout:
        def __init__(self, lines):
            self._lines = list(lines)

        async def readline(self):
            return self._lines.pop(0) if self._lines else b""

    class FakeProc:
        def __init__(self):
            self.stdout = FakeStdout(
                [
                    _delta_line("Looking… "),
                    _tool_start_line("toolu_a", "Read", {"file_path": "src/x.py"}),
                    _tool_result_line("toolu_a", "file body"),  # 9 chars
                    _delta_line("done"),
                ]
            )

        async def wait(self):
            return 0

    async def fake_exec(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(provider.asyncio, "create_subprocess_exec", fake_exec)

    events: list[dict] = []
    monkeypatch.setattr(provider.renderer, "emit", events.append)

    chunks = [
        c async for c in provider._claude_cli_stream([{"role": "user", "content": "hi"}], "sp")
    ]

    # Tool lifecycle surfaced as display events, in order, with matching index.
    starts = [e for e in events if e["type"] == "tool_call_start"]
    ends = [e for e in events if e["type"] == "tool_call_end"]
    assert len(starts) == 1 and len(ends) == 1
    assert starts[0]["name"] == "Read"
    assert starts[0]["input"] == {"file_path": "src/x.py"}  # full input surfaced
    assert starts[0]["index"] == ends[0]["index"]
    assert ends[0]["is_error"] is False
    assert ends[0]["chars"] == 9

    # The tool is NOT yielded as a tool_calls chunk — only text streams through,
    # so the agent loop never tries to execute the subprocess's tools itself.
    assert all(getattr(c.choices[0].delta, "tool_calls", None) is None for c in chunks)
    text = "".join(c.choices[0].delta.content or "" for c in chunks)
    assert text == "Looking… done"


@pytest.mark.asyncio
async def test_claude_cli_stream_chunk_shape(monkeypatch):
    """_claude_cli_stream spawns `claude -p` in stream-json mode and yields
    OpenAI-format chunks built from each text_delta — true token streaming.

    BDD: a claude subprocess is spawned with -p and --output-format stream-json,
    each content_block_delta becomes a text_delta chunk in the same OpenAI shape
    (choices[0].delta / finish_reason) the agent loop already consumes.
    """
    spawned = {}

    class FakeStdout:
        def __init__(self, lines):
            self._lines = list(lines)

        async def readline(self):
            return self._lines.pop(0) if self._lines else b""

    class FakeProc:
        def __init__(self):
            # A realistic stream: init noise, two token deltas, then a result.
            self.stdout = FakeStdout(
                [
                    b'{"type":"system","subtype":"init"}\n',
                    _delta_line("Hello "),
                    _delta_line("world"),
                    b'{"type":"result","subtype":"success","result":"Hello world"}\n',
                ]
            )

        async def wait(self):
            return 0

    async def fake_exec(*args, **kwargs):
        spawned["args"] = args
        return FakeProc()

    monkeypatch.setattr(provider.asyncio, "create_subprocess_exec", fake_exec)

    chunks = [
        c async for c in provider._claude_cli_stream([{"role": "user", "content": "hi"}], "sp")
    ]

    # Spawned the claude binary in -p stream-json mode.
    assert spawned["args"][0] == "claude"
    assert "-p" in spawned["args"]
    assert "--output-format" in spawned["args"]
    assert "stream-json" in spawned["args"]
    # A permission mode is passed so the print-mode subprocess can write/run
    # without an interactive prompt it cannot show.
    assert "--permission-mode" in spawned["args"]
    assert provider.CLI_PERMISSION_MODE in spawned["args"]

    # Every chunk is the OpenAI-format shape the loop reads.
    for c in chunks:
        assert isinstance(c, SimpleNamespace)
        assert hasattr(c.choices[0].delta, "content")

    # Only the two token deltas contribute text — init/result noise is dropped.
    text = "".join(c.choices[0].delta.content or "" for c in chunks)
    assert text == "Hello world"

    # The final chunk carries a finish_reason so the loop terminates the turn.
    assert chunks[-1].choices[0].finish_reason == "stop"


@pytest.mark.asyncio
async def test_claude_cli_stream_permission_mode_is_overridable(monkeypatch):
    """CLI_PERMISSION_MODE (from CLAUDE_CLI_PERMISSION_MODE) sets --permission-mode."""
    spawned = {}

    class FakeStdout:
        async def readline(self):
            return b""

    class FakeProc:
        stdout = FakeStdout()

        async def wait(self):
            return 0

    async def fake_exec(*args, **kwargs):
        spawned["args"] = args
        return FakeProc()

    monkeypatch.setattr(provider.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(provider, "CLI_PERMISSION_MODE", "acceptEdits")

    async for _ in provider._claude_cli_stream([{"role": "user", "content": "hi"}], "sp"):
        pass

    args = spawned["args"]
    assert args[args.index("--permission-mode") + 1] == "acceptEdits"


# ── _messages_to_prompt: multimodal / list content (CLI fork is text-only) ───


def test_messages_to_prompt_flattens_list_content():
    """A multimodal user message (text + image blocks) must not crash the
    text-only CLI fork: text parts are kept, image blocks become a placeholder.

    BDD: Given a user message whose content is a list of {type:text} and
    {type:image_url} blocks, When _messages_to_prompt renders it, Then the text
    survives and the image is replaced with a clear '[image omitted ...]' note.
    """
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "what is this?"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
            ],
        }
    ]
    prompt = provider._messages_to_prompt("sys", messages)
    assert "what is this?" in prompt
    assert "image omitted" in prompt
    # The raw base64 payload must never leak into the flattened text prompt.
    assert "QUJD" not in prompt


def test_messages_to_prompt_plain_string_unchanged():
    """A plain-string content message renders exactly as before (no regression)."""
    prompt = provider._messages_to_prompt("sys", [{"role": "user", "content": "hello"}])
    assert "User: hello" in prompt
    assert "System: sys" in prompt


# ── _claude_cli_stream: large stream-json lines must not overflow readline ────


@pytest.mark.integration
async def test_cli_stream_reader_handles_lines_over_64kb():
    """A single stream-json line can exceed asyncio's default 64KB readline cap.

    `claude -p` echoes the image it read back as a base64 block, so one NDJSON
    line routinely runs past 64KB (and far larger with our 5MB image cap). The
    default StreamReader limit makes readline() raise LimitOverrunError mid-turn,
    crashing the run. _claude_cli_stream must spawn the subprocess with a raised
    `limit` so such lines stream through intact.

    BDD: Given a subprocess emitting a single line well over 64KB, When it is read
    with provider._CLI_STREAM_LIMIT, Then the whole line arrives without error;
    And the asyncio default would have raised, proving the cap is the fix.
    """
    import asyncio

    big = 200_000  # comfortably over the 65_536-byte default

    # The default limit must actually fail on this line (guards the test's point).
    proc = await asyncio.create_subprocess_exec(
        "python3",
        "-c",
        f"print('A' * {big})",
        stdout=asyncio.subprocess.PIPE,
    )
    assert proc.stdout is not None
    with pytest.raises(ValueError):
        await proc.stdout.readline()
    await proc.wait()

    # The provider's raised limit must read the whole line cleanly.
    proc = await asyncio.create_subprocess_exec(
        "python3",
        "-c",
        f"print('A' * {big})",
        stdout=asyncio.subprocess.PIPE,
        limit=provider._CLI_STREAM_LIMIT,
    )
    assert proc.stdout is not None
    line = await proc.stdout.readline()
    await proc.wait()
    assert len(line.strip()) == big
