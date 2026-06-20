import inspect
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


@pytest.mark.asyncio
async def test_claude_cli_stream_chunk_shape(monkeypatch):
    """_claude_cli_stream spawns `claude -p` and yields OpenAI-format chunks.

    BDD: a claude subprocess is spawned with the -p flag, and text chunks from
    the CLI are yielded in the same OpenAI-format shape (choices[0].delta /
    finish_reason) the agent loop already consumes.
    """
    spawned = {}

    class FakeStdout:
        def __init__(self, lines):
            self._lines = list(lines)

        async def readline(self):
            return self._lines.pop(0) if self._lines else b""

    class FakeProc:
        def __init__(self):
            self.stdout = FakeStdout([b"Hello ", b"world\n"])

        async def wait(self):
            return 0

    async def fake_exec(*args, **kwargs):
        spawned["args"] = args
        return FakeProc()

    monkeypatch.setattr(provider.asyncio, "create_subprocess_exec", fake_exec)

    chunks = [
        c async for c in provider._claude_cli_stream([{"role": "user", "content": "hi"}], "sp")
    ]

    # Spawned the claude binary with the -p flag.
    assert spawned["args"][0] == "claude"
    assert "-p" in spawned["args"]

    # Every chunk is the OpenAI-format shape the loop reads.
    for c in chunks:
        assert isinstance(c, SimpleNamespace)
        assert hasattr(c.choices[0].delta, "content")

    text = "".join(c.choices[0].delta.content or "" for c in chunks)
    assert "Hello" in text and "world" in text

    # The final chunk carries a finish_reason so the loop terminates the turn.
    assert chunks[-1].choices[0].finish_reason == "stop"
