Status: not started

# Phase 2 — The Conversation Loop

## Goal

Create `src/agent.py` with a `run_agent(task)` coroutine that seeds message history, calls `call_model` inside an outer/inner loop skeleton, appends the assistant reply, and returns the full history — stopping after the first text reply with no tools.

## Files changed

| File | Change |
|---|---|
| `src/agent.py` | New file: `run_agent` coroutine with outer/inner while-loop, `messages` list as state, and `has_more_tool_calls = False` stop condition |
| `tests/test_agent.py` | New file: three async tests monkeypatching `provider.call_model` to verify history shape, stop-after-one-call, and full-history forwarding |

## Order of operations

1. Write `tests/test_agent.py` with the three tests (`test_run_agent_returns_user_and_assistant`, `test_run_agent_stops_after_text_reply`, `test_run_agent_passes_full_history_to_model`). Run and confirm `ModuleNotFoundError: No module named 'agent'`.
2. Create `src/agent.py`: define `MAX_ITERATIONS = 30`, `run_agent` with the outer `while True` / inner `while has_more_tool_calls` skeleton, single `call_model` call, assistant-append, `has_more_tool_calls = False`, and `break`.
3. Run tests again — all three should pass.
4. Optionally run `scratch_phase2.py` at the repo root to verify against the live CLI.

## Verification

- [ ] Tests added: `tests/test_agent.py`
- [ ] Run: `uv run pytest tests/test_agent.py -v` — expect `3 passed`
- [ ] Live smoke test: `uv run python scratch_phase2.py` — prints `[USER]` and `[ASSISTANT]` lines
- [ ] BDD gate (red before, green after):

```gherkin
Feature: The conversation loop
  run_agent seeds the message history with the user task, calls the model,
  appends the reply, and stops when the model returns plain text with no
  tool calls. The full history is passed to the model on every call.

  Scenario: A plain text reply produces exactly [user, assistant] and stops
    Given a scripted model that returns "Hi! How can I help?" with finish_reason "stop"
    When run_agent("say hi") completes
    Then the returned history has exactly 2 messages
    And messages[0] equals {"role": "user", "content": "say hi"}
    And messages[1] has role "assistant" and content "Hi! How can I help?"
    And no message in the history has role "tool"

  Scenario: The full prior history is sent on each model call
    Given a capturing model that records the messages it receives
    When run_agent("hello") completes
    Then the model received exactly one call
    And the messages list passed to the model contains the user message as its first element
    And the system_prompt argument is a non-empty string on every call

  Scenario: The loop makes exactly one model call for a no-tool task
    Given a counting model that increments a call counter and returns "Done."
    When run_agent("do something") completes
    Then the call counter is exactly 1
    And the loop did not re-enter after receiving the plain text reply
```

## Notes / open questions

- The outer loop `break` and `has_more_tool_calls = False` are stubs — they exist to carry the structure forward so Phases 4–5 can fill in tool detection without restructuring.
- Monkeypatch `provider.call_model` (the module attribute), not `agent.call_model`, because `agent.py` uses `from provider import call_model`. Patching the source module is the idiomatic approach.
- `scratch_phase2.py` is throwaway — do not commit it.

---

**Tutorial build step 2 of 32** · ← [Phase 1 — Talk to a Model](./phase-01-talk-to-a-model.md) · [Phase 3 — Streaming Responses](./phase-03-streaming.md) →
