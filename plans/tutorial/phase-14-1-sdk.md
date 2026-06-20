Status: done
Branch: step/phase-14-1-sdk

# Phase 14.1 — The SDK

## Goal

Expose `run_agent` as a proper library entry point by adding `src/sdk.py`, which wraps the emit() seam to collect all typed events into a list alongside the returned message history so callers can drive the agent in-process without parsing stdout.

## Files changed

| File | Change |
|---|---|
| `src/sdk.py` | New file — `run_agent_collecting(task)` monkey-patches `renderer.emit` for the duration of a single call to collect events, restoring the original emitter in `finally` |
| `tests/test_sdk.py` | New file — unit test that mocks `agent.stream_response` and asserts events list contains `text_delta`, ends with `agent_end`, and message history includes user + assistant turns |

## Order of operations

1. Read `src/agent.py` to confirm `run_agent` signature (`async def run_agent(task: str) -> list[dict]`) and that it calls `emit()` from renderer.
2. Read `src/renderer.py` to confirm `emit` is a module-level name that can be replaced at runtime.
3. Create `src/sdk.py` with `run_agent_collecting`: save `_renderer.emit`, install a collecting wrapper that appends to `collected` and forwards to the original, `await run_agent(task)` in a try/finally, restore original emit, return `(collected, messages)`.
4. Write `tests/test_sdk.py` using the `fake_stream` mock pattern from Phase 9: patch `agent.stream_response` with an async generator yielding one stop chunk, call `run_agent_collecting("ping")`, assert event types and message history shape.
5. Run tests red (before sdk.py exists) then green (after) to confirm the BDD gate works.

## Verification

- [ ] Tests added: `tests/test_sdk.py`
- [ ] Run: `uv run pytest tests/test_sdk.py -v`
- [ ] Script smoke test: `uv run my_script.py` (drives `run_agent_collecting` against live API and prints event summary + message history)
- [ ] BDD acceptance:

```gherkin
Scenario: SDK caller receives typed events in order with matching message history
  Given the agent is called via run_agent_collecting() with a simple task
  When the agent completes (no real API call — stream_response is mocked)
  Then the events list contains at least one text_delta event
  And the events list contains a tool_call_start followed by a tool_call_end
       for each tool call, in that order
  And the final event has type "agent_end" with status "ok"
  And the returned message history contains the same assistant turns and
       tool results that a direct run_agent() call would return
```

## Notes / open questions

- The monkey-patch approach is intentionally minimal: it mutates `_renderer.emit` on the module object, which works because `agent.py` resolves `emit` at call time via the module reference. A production SDK would inject a callback directly into `run_agent` — that refactor is deferred to Phase 15 (steering), where a first-class callback becomes necessary.
- Restoring `renderer.emit` in `finally` means exceptions in `run_agent` do not leave the renderer in a broken state.
- Concurrent in-process calls to `run_agent_collecting` would race on the module-level `emit` replacement — note this limitation in a docstring; it is acceptable for a single-threaded async event loop.

---

**Tutorial build step 27 of 32** · ← [Phase 13.6 — Custom Models & Providers](./phase-13-6-models-and-providers.md) · [Phase 14.2 — RPC Mode](./phase-14-2-rpc-mode.md) →
