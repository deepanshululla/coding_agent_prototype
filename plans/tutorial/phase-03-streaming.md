Status: done
Branch: step/phase-03-streaming

# Phase 3 — Streaming Responses

## Goal

Add a `stream_response` async generator to `src/provider.py` that consumes `claude -p --output-format stream-json` events and yields OpenAI-format chunks, then update `src/agent.py`'s inner loop to accumulate `text_buf` and `finish_reason` from those chunks and print tokens as they arrive.

## Files changed

| File | Change |
|---|---|
| `src/provider.py` | Add `_chunk()` helper, `ModelClient.stream()` async generator (stream-json backend), and module-level `stream_response` async generator; keep `call_model` for backward compatibility |
| `src/agent.py` | Replace `call_model` call in inner loop with `async for chunk in stream_response(...)`, accumulate `text_buf` and `finish_reason`, print deltas live with `end="", flush=True` |
| `tests/test_agent.py` | Add `test_streaming_text_accumulates` using a `ScriptedLLM` helper that feeds canned chunks through `stream_response` |

## Order of operations

1. Write the failing test `test_streaming_text_accumulates` in `tests/test_agent.py` (uses `ScriptedLLM` and `_chunk` helpers). Confirm it fails.
2. Add `_chunk(content, finish_reason)` helper to `src/provider.py` (builds `SimpleNamespace`-based OpenAI chunk).
3. Add `ModelClient.stream()` async generator: subprocess with `--output-format stream-json --verbose`, parse newline-delimited JSON, yield `_chunk` for `assistant` and `result` event types.
4. Add module-level `stream_response` async generator delegating to `_client.stream()`.
5. Update `src/agent.py` inner loop: replace `call_model` with `async for chunk in stream_response(...)`, accumulate `text_buf` via `delta.content`, track `finish_reason = choice.finish_reason or finish_reason`, print `delta.content` live, print newline after the loop.
6. Run `test_streaming_text_accumulates` — should pass. Run full suite to confirm no regressions.

## Verification

- [ ] Tests added/updated: `tests/test_agent.py` (`test_streaming_text_accumulates`)
- [ ] Run: `uv run pytest tests/test_agent.py::test_streaming_text_accumulates -v` — expect `PASSED`
- [ ] Full suite: `uv run pytest tests/test_agent.py -v` — no regressions
- [ ] Live run: `uv run main.py "count to five slowly"` — tokens appear incrementally, not all at once
- [ ] BDD gate (red before, green after):

```gherkin
Feature: Streaming accumulation
  stream_response yields OpenAI-format chunks; run_agent accumulates content
  fragments into a single assistant message and carries finish_reason forward
  from the one chunk that sets it. An empty stream must still terminate cleanly.

  Scenario: Multiple text fragments are joined into one assistant message
    Given a scripted model that yields chunks with content "one", ", ", "two", ", ", "three"
    And a final chunk with finish_reason "stop"
    When run_agent("count to three") completes
    Then messages[1] has role "assistant"
    And messages[1]["content"] equals "one, two, three"
    And "tool_calls" is not present in messages[1]

  Scenario: finish_reason is carried forward from the single chunk that sets it
    Given a scripted model that yields five content chunks all with finish_reason None
    And then a final empty chunk with finish_reason "stop"
    When run_agent processes the stream
    Then the accumulated finish_reason after the loop is "stop"
    And the assistant message content is the concatenation of all five content strings
    And the loop exits cleanly without reading past the finish chunk

  Scenario: An empty stream with no content chunks still terminates without error
    Given a scripted model that yields only a single chunk with finish_reason "stop" and no content
    When run_agent("say nothing") completes
    Then no exception is raised
    And the returned history has exactly 2 messages
    And messages[1] has role "assistant"
    And messages[1]["content"] is None or an empty string
```

## Notes / open questions

- The `_chunk()` helper uses `SimpleNamespace` to avoid importing any provider SDK; Phase 11 replaces the class body with `litellm.acompletion` which returns real chunk objects with the same shape.
- The `ScriptedLLM` test harness (introduced here) becomes the foundation for BDD testing in Phase 9 — keep it reusable.
- `choice.finish_reason or finish_reason` idiom: most chunks have `finish_reason=None`; this silently carries the last non-None value without an extra `if`.
- The `claude -p` CLI's `stream-json` format emits `assistant` events (with text blocks) and a `result` event at the end; tool-call events are not part of this format — that is addressed by Phase 11 (LiteLLM).

---

**Tutorial build step 3 of 32** · ← [Phase 2 — The Conversation Loop](./phase-02-the-agent-loop.md) · [Phase 4 — Your First Tool](./phase-04-your-first-tool.md) →
