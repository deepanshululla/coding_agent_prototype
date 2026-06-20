"""Phase 16 — Context Compaction.

BDD scenario:

  Scenario: Compaction keeps the agent coherent after a long task
    Given a long task whose message history exceeds the compaction threshold
    When the agent continues after compaction triggers
    Then the context sent to the model is shorter than the full message history
    And the agent proceeds coherently without losing the essential facts from
      prior turns

The hook is ``compact_if_needed(messages, system_prompt)`` in the inner loop. The
invariant under test: the source-of-truth ``messages`` is never mutated, and the
context handed to ``stream_response`` is shorter once the token estimate crosses
the threshold ladder. Thresholds are lowered to tiny values so a small fixture
history can trip them deterministically without an external API.
"""

import json

import pytest

import agent
import compaction
from policy import PolicyEngine
from provider import _chunk


class ScriptedLLM:
    """Stand-in for stream_response: yields one scripted turn per call and
    records the messages it was handed on each call."""

    def __init__(self, turns):
        self._turns = list(turns)
        self._index = 0
        self.seen_messages = []

    def __call__(self, messages, system_prompt, model=None):
        # Snapshot the exact list handed to the provider for this turn.
        self.seen_messages.append(list(messages))
        turn = self._turns[self._index]
        self._index += 1

        async def _gen():
            for chunk in turn:
                yield chunk

        return _gen()


def _padded_history(n_tool_results: int) -> list[dict]:
    """Build a message history with the original task plus many bulky tool
    results, long enough to exceed a lowered threshold."""
    messages: list[dict] = [
        {"role": "user", "content": "The secret code is BANANA-42. Remember it."}
    ]
    for i in range(n_tool_results):
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"c{i}",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": f'{{"path": "f{i}"}}'},
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": f"c{i}",
                "content": "X" * 500,  # bulky stale output
            }
        )
    return messages


# ── Unit: estimation and the no-mutation invariant ──────────────────────────


def test_passthrough_returns_same_object_below_threshold(monkeypatch):
    monkeypatch.setattr(compaction, "PASSTHROUGH_THRESHOLD", 10_000_000)
    msgs = _padded_history(3)

    import asyncio

    out = asyncio.run(compaction.compact_if_needed(msgs, "sys"))

    assert out is msgs  # exact same object — no allocation on passthrough


def test_drop_stale_strategy_shortens_and_does_not_mutate(monkeypatch):
    # Force the drop-stale band: estimate must land in [PASSTHROUGH, DROP).
    monkeypatch.setattr(compaction, "PASSTHROUGH_THRESHOLD", 100)
    monkeypatch.setattr(compaction, "DROP_THRESHOLD", 10_000_000)
    monkeypatch.setattr(compaction, "KEEP_RECENT_TOOL_RESULTS", 1)

    msgs = _padded_history(5)
    before = json.dumps(msgs)
    estimate_before = compaction.estimate_tokens(msgs)

    import asyncio

    out = asyncio.run(compaction.compact_if_needed(msgs, "sys"))

    # The returned list is a different object and estimates fewer tokens.
    assert out is not msgs
    assert compaction.estimate_tokens(out) < estimate_before
    # Source-of-truth never mutated.
    assert json.dumps(msgs) == before
    # Every tool_call still has a matching tool message (well-formed history).
    tool_msgs = [m for m in out if m["role"] == "tool"]
    assert len(tool_msgs) == 5  # placeholders kept, just shorter content
    assert any("elided" in m["content"] for m in tool_msgs)


def test_keep_recent_only_preserves_first_user_turn(monkeypatch):
    monkeypatch.setattr(compaction, "PASSTHROUGH_THRESHOLD", 100)
    monkeypatch.setattr(compaction, "DROP_THRESHOLD", 101)
    monkeypatch.setattr(compaction, "SUMMARISE_THRESHOLD", 102)
    monkeypatch.setattr(compaction, "KEEP_RECENT_MESSAGES", 4)

    msgs = _padded_history(8)

    import asyncio

    out = asyncio.run(compaction.compact_if_needed(msgs, "sys"))

    assert len(out) < len(msgs)
    # The original task (carrying the secret code) survives compaction.
    assert out[0]["role"] == "user"
    assert "BANANA-42" in out[0]["content"]
    # The tail must not start on an orphan tool message.
    assert out[1]["role"] != "tool"


@pytest.mark.asyncio
async def test_summarise_strategy_uses_llm_and_keeps_task(monkeypatch):
    """The summarise band calls stream_response once for a prose summary and
    folds it into a synthetic user turn, keeping the first task and recent tail."""
    monkeypatch.setattr(compaction, "PASSTHROUGH_THRESHOLD", 100)
    monkeypatch.setattr(compaction, "DROP_THRESHOLD", 101)
    monkeypatch.setattr(compaction, "SUMMARISE_THRESHOLD", 10_000_000)
    monkeypatch.setattr(compaction, "KEEP_RECENT_MESSAGES", 2)

    async def fake_stream(messages, system_prompt, model=None):
        yield _chunk(content="- read 8 files; secret code BANANA-42")
        yield _chunk(finish_reason="stop")

    monkeypatch.setattr(compaction, "stream_response", fake_stream)

    msgs = _padded_history(8)
    out = await compaction.compact_if_needed(msgs, "sys")

    assert len(out) < len(msgs)
    assert out[0]["role"] == "user" and "BANANA-42" in out[0]["content"]
    # A synthetic summary user turn was inserted.
    assert any(
        m["role"] == "user" and "[summary of earlier conversation]" in (m.get("content") or "")
        for m in out
    )


@pytest.mark.asyncio
async def test_summarise_falls_back_to_keep_recent_on_failure(monkeypatch):
    """If the summary LLM call yields nothing, compaction degrades to
    keep-recent-only rather than crashing the agent loop."""
    monkeypatch.setattr(compaction, "PASSTHROUGH_THRESHOLD", 100)
    monkeypatch.setattr(compaction, "DROP_THRESHOLD", 101)
    monkeypatch.setattr(compaction, "SUMMARISE_THRESHOLD", 10_000_000)
    monkeypatch.setattr(compaction, "KEEP_RECENT_MESSAGES", 2)

    async def empty_stream(messages, system_prompt, model=None):
        yield _chunk(finish_reason="stop")

    monkeypatch.setattr(compaction, "stream_response", empty_stream)

    msgs = _padded_history(8)
    out = await compaction.compact_if_needed(msgs, "sys")

    assert len(out) < len(msgs)
    assert out[0]["role"] == "user" and "BANANA-42" in out[0]["content"]
    # No summary turn — the fallback kept verbatim tail instead.
    assert not any(
        "[summary of earlier conversation]" in (m.get("content") or "") for m in out
    )


# ── Integration: the agent loop sends the compacted context ──────────────────


@pytest.mark.asyncio
async def test_agent_sends_compacted_context_to_provider(monkeypatch):
    """BDD gate: after the threshold trips, stream_response receives a list
    shorter than the full message history, and the run still completes."""
    # Lower thresholds so the small fixture trips the drop-stale band.
    monkeypatch.setattr(compaction, "PASSTHROUGH_THRESHOLD", 100)
    monkeypatch.setattr(compaction, "DROP_THRESHOLD", 10_000_000)
    monkeypatch.setattr(compaction, "KEEP_RECENT_TOOL_RESULTS", 1)

    scripted = ScriptedLLM(
        [[_chunk(content="The code is BANANA-42."), _chunk(finish_reason="stop")]]
    )
    monkeypatch.setattr(agent, "stream_response", scripted)
    monkeypatch.setattr(agent, "_policy", PolicyEngine(rules=[], default="allow"))

    # Seed run_agent with a pre-built bulky history via pending_messages so the
    # very first inner pass already exceeds the threshold.
    pre = _padded_history(6)[1:]  # everything after the initial task message
    messages = await agent.run_agent(
        "The secret code is BANANA-42. Remember it.",
        pending_messages=list(pre),
    )

    # The provider was called at least once and the context it saw was shorter
    # than the full history that existed at that point.
    assert scripted.seen_messages, "provider was never called"
    sent = scripted.seen_messages[0]
    sent_tokens = compaction.estimate_tokens(sent)
    full_tokens = compaction.estimate_tokens(messages)
    assert sent_tokens < full_tokens
    # The agent proceeds coherently: it answered, and the original fact is
    # still in the real (uncompacted) history.
    assert any(
        m["role"] == "user" and "BANANA-42" in (m.get("content") or "")
        for m in messages
    )


@pytest.mark.asyncio
async def test_no_compaction_below_threshold_keeps_full_history(monkeypatch):
    """With a huge passthrough threshold, the provider gets the full history
    object unchanged — no regression of prior phases."""
    monkeypatch.setattr(compaction, "PASSTHROUGH_THRESHOLD", 10_000_000)

    scripted = ScriptedLLM([[_chunk(content="hi"), _chunk(finish_reason="stop")]])
    monkeypatch.setattr(agent, "stream_response", scripted)

    messages = await agent.run_agent("say hi")

    # The provider saw exactly the single user turn (passthrough, same content).
    assert scripted.seen_messages[0] == [{"role": "user", "content": "say hi"}]
    assert messages[-1]["content"] == "hi"
