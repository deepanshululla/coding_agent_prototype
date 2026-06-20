Status: not started

# Phase 11 — Add LiteLLM (Multi-Provider)

## Goal

Replace the `claude -p` subprocess backend in `src/provider.py` with `litellm.acompletion` behind the same `stream_response` signature so any supported provider can be selected by changing the `MODEL` constant — with zero changes to the agent loop, tools, prompts, or existing tests.

## Files changed

| File | Change |
|---|---|
| `src/provider.py` | Swap `ModelClient.stream` body from subprocess to `litellm.acompletion(..., stream=True)`; then collapse the class to produce the final form: only `MODEL`, `MAX_TOKENS`, and the `stream_response` async generator function |
| `tests/test_provider.py` | New file — `test_stream_response_is_async_generator` asserts `inspect.isasyncgenfunction(provider.stream_response)` |
| `pyproject.toml` | Add `litellm` dependency via `uv add litellm` |

## Order of operations

1. Run `uv add litellm` to add the dependency and update `pyproject.toml` / `uv.lock`.
2. Write `tests/test_provider.py` with `test_stream_response_is_async_generator`; confirm it passes already (the function is already an async generator) or adjust once the swap is done.
3. Swap `ModelClient.stream` to call `litellm.acompletion(model=MODEL, messages=full_messages, tools=TOOLS_SCHEMA, tool_choice="auto", max_tokens=MAX_TOKENS, stream=True)` and yield each chunk unchanged.
4. Run `uv run pytest tests/test_agent.py -v` — all 4 loop tests must pass without modification (they monkeypatch `agent.stream_response` and never call the real backend).
5. Collapse `ModelClient` into the final form: a standalone `stream_response` async generator function that calls `litellm.acompletion` directly, with `MODEL` and `MAX_TOKENS` as module-level constants.
6. Add `ANTHROPIC_API_KEY=...` (or another provider key) to `.env` and run `uv run main.py "list all .py files in src/"` to confirm the live backend works.

## Verification

- [ ] Tests added/updated: `tests/test_provider.py` (`test_stream_response_is_async_generator` passes)
- [ ] Existing suite unchanged: `uv run pytest tests/test_agent.py -v` — 4 passed, no modifications to test file
- [ ] CLI / service run: `uv run main.py "list all .py files in src/"` with a valid provider API key in `.env`
- [ ] Provider swap smoke test: change `MODEL` to `"gpt-4o"` (with `OPENAI_API_KEY` set) and re-run the same CLI command — identical behavior
- [ ] BDD acceptance criteria (run before/after the build as a red/green gate):

```gherkin
Feature: Backend swap invariance
  Replacing the claude -p subprocess with litellm.acompletion behind the same
  stream_response signature leaves the loop, tools, and tests entirely unchanged.

  Scenario: the existing loop scenarios pass unchanged after swapping to LiteLLM
    Given src/provider.py is updated to call litellm.acompletion instead of claude -p
    And agent.stream_response is monkeypatched with ScriptedLLM as in every other test
    When the full tests/test_agent.py suite runs
    Then all 4 loop tests pass without modification
    And no test imports litellm directly (the backend is hidden behind stream_response)

  Scenario: stream_response stays an async generator yielding the same chunk shape
    Given the LiteLLM-backed src/provider.py is in place
    When inspect.isasyncgenfunction(provider.stream_response) is evaluated
    Then the result is True
    And each chunk yielded has the attribute path chunk.choices[0].delta.content or chunk.choices[0].delta.tool_calls
    And each chunk yielded has the attribute chunk.choices[0].finish_reason

  Scenario: changing the MODEL string routes to a different provider with no loop change
    Given MODEL in src/provider.py is set to "gpt-4o"
    And agent.stream_response is monkeypatched so no real network call is made
    When run_agent is called and the ScriptedLLM produces a plain-text answer
    Then run_agent completes successfully
    And src/agent.py, src/tools.py, and src/prompts.py are identical to their Phase 9 versions (no edits required)

  Scenario: tools schema is passed through to litellm.acompletion
    Given the LiteLLM-backed provider is in place
    And litellm.acompletion is monkeypatched to capture its keyword arguments
    When stream_response is called with a messages list and a system prompt
    Then litellm.acompletion is called with tools=TOOLS_SCHEMA
    And litellm.acompletion is called with tool_choice="auto"
    And litellm.acompletion is called with stream=True
```

## Notes / open questions

- The `ModelClient` class is scaffolding that exists only to make the swap teachable. Once the swap is done the class adds no value — collapse it as described in step 5.
- The system prompt is prepended as `{"role": "system", "content": system_prompt}` inside `stream_response`; it is NOT in the `messages` list that `run_agent` manages. Both layers must agree on this.
- `litellm` routes by model string prefix: `"claude-*"` → Anthropic, `"gpt-*"` → OpenAI, `"gemini/*"` → Google. No other configuration is needed beyond the matching API key in the environment.
- `load_dotenv()` in `main.py` ensures `.env` keys are read before `litellm` is called. If running tests that exercise the real backend, set the key in the shell environment or `.env` first.

---

**Tutorial build step 15 of 32** · ← [Phase 10.5 — Keybindings & Themes](./phase-10-5-keys-themes.md) · [Phase 12.1 — The Security Model](./phase-12-1-security-model.md) →
