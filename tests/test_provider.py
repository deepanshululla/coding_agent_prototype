import pytest

import provider


@pytest.mark.asyncio
async def test_call_model_returns_text(monkeypatch):
    """call_model should return the text content from the model's reply."""

    async def fake_complete(self, messages, system_prompt):
        return "Hello from the model!"

    monkeypatch.setattr(provider.ModelClient, "complete", fake_complete)

    result = await provider.call_model(
        messages=[{"role": "user", "content": "say hi"}],
        system_prompt="You are a helpful assistant.",
    )

    assert result == "Hello from the model!"


@pytest.mark.asyncio
async def test_call_model_passes_latest_message(monkeypatch):
    """ModelClient.complete receives the messages list and system prompt intact."""
    captured: dict = {}

    async def capturing_complete(self, messages, system_prompt):
        captured["messages"] = messages
        captured["system_prompt"] = system_prompt
        return "ok"

    monkeypatch.setattr(provider.ModelClient, "complete", capturing_complete)

    await provider.call_model(
        messages=[{"role": "user", "content": "hello"}],
        system_prompt="You are a test assistant.",
    )

    assert captured["messages"][-1] == {"role": "user", "content": "hello"}
    assert captured["system_prompt"] == "You are a test assistant."


@pytest.mark.asyncio
async def test_call_model_empty_reply_does_not_raise(monkeypatch):
    """An empty string reply from the model is returned, not treated as an error."""

    async def empty_complete(self, messages, system_prompt):
        return ""

    monkeypatch.setattr(provider.ModelClient, "complete", empty_complete)

    result = await provider.call_model(
        messages=[{"role": "user", "content": "say nothing"}],
        system_prompt="You are a silent assistant.",
    )

    assert result == ""
