import pytest


@pytest.mark.asyncio
async def test_run_agent_returns_user_and_assistant(monkeypatch):
    """The loop should seed messages with the user turn and append exactly
    one assistant reply when the model returns plain text."""
    import provider  # import the module so monkeypatch can target it

    async def fake_call_model(messages, system_prompt):
        return "Hi! How can I help?"

    monkeypatch.setattr(provider, "call_model", fake_call_model)

    from agent import run_agent

    history = await run_agent("say hi")

    assert len(history) == 2
    assert history[0] == {"role": "user", "content": "say hi"}
    assert history[1] == {"role": "assistant", "content": "Hi! How can I help?"}
    assert not any(m["role"] == "tool" for m in history)


@pytest.mark.asyncio
async def test_run_agent_stops_after_text_reply(monkeypatch):
    """The loop must stop after a single text reply — no further calls."""
    import provider

    call_count = 0

    async def counting_call_model(messages, system_prompt):
        nonlocal call_count
        call_count += 1
        return "Done."

    monkeypatch.setattr(provider, "call_model", counting_call_model)

    from agent import run_agent

    await run_agent("do something")

    assert call_count == 1, f"Expected 1 model call, got {call_count}"


@pytest.mark.asyncio
async def test_run_agent_passes_full_history_to_model(monkeypatch):
    """Each call to the model should receive the full message history so far
    and a non-empty system prompt."""
    import provider

    received_messages: list = []
    system_prompts: list = []
    call_count = 0

    async def capturing_call_model(messages, system_prompt):
        nonlocal call_count
        call_count += 1
        received_messages.extend(messages)
        system_prompts.append(system_prompt)
        return "Response."

    monkeypatch.setattr(provider, "call_model", capturing_call_model)

    from agent import run_agent

    await run_agent("hello")

    # The model should have been called exactly once for a no-tool task.
    assert call_count == 1
    # The model should have received the user message as the first element.
    assert received_messages[0] == {"role": "user", "content": "hello"}
    # The system prompt must be a non-empty string on every call.
    assert all(isinstance(p, str) and p for p in system_prompts)
