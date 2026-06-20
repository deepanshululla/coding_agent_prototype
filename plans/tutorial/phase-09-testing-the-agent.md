Status: not started

# Phase 9 — Testing the Agent

## Goal

Build a `ScriptedLLM` / `_chunk` / `_tc` harness in `tests/test_agent.py` that monkeypatches `agent.stream_response` with scripted canned chunks, then write three core behavioral tests that verify the stop condition, streaming fragment buffering, and parallel tool dispatch — all without any network call or API key.

## Files changed

| File | Change |
|---|---|
| `tests/test_agent.py` | Add `_chunk` and `_tc` builder functions, `ScriptedLLM` class, and three behavioral tests: `test_plain_text_turn_stops`, `test_tool_call_then_stop`, `test_multiple_parallel_tool_calls` |

## Order of operations

1. Add `_chunk(content, tool_calls, finish_reason)` using `types.SimpleNamespace` to build one OpenAI-style streaming chunk.
2. Add `_tc(index, id, name, arguments)` using `types.SimpleNamespace` to build one tool-call fragment inside a delta.
3. Add the `ScriptedLLM` class: stores a list of turn-lists, pops from the front on each `__call__`, and returns an async generator that yields the turn's chunks.
4. Write `test_plain_text_turn_stops`: script one text-only turn with `finish_reason="stop"`, assert exactly a user + assistant message, no `tool_calls` key, no `role: "tool"` messages.
5. Write `test_tool_call_then_stop`: script a `list_dir` tool call with split argument fragments across two chunks (turn 1) then a text summary (turn 2); assert fragment buffering, correct `tool_call_id` linkage, and real filesystem execution.
6. Write `test_multiple_parallel_tool_calls`: script two `read_file` calls in one turn using different `index` values; assert both `tool_call_id` values appear in the history and both file contents appear in results.
7. Run `uv run pytest -q` and confirm all 17 tests pass (including the 3 new ones).

## Verification

- [ ] Tests added/updated: `tests/test_agent.py` (3 new behavioral tests added to existing 2)
- [ ] CLI / service run: `uv run pytest -q` outputs `17 passed` (or more) in under 5 seconds
- [ ] Offline confirmation: unset `ANTHROPIC_API_KEY` and re-run — all tests still pass (no network)
- [ ] BDD acceptance criteria (run before/after the build as a red/green gate):

```gherkin
Feature: Deterministic offline testing with ScriptedLLM
  The ScriptedLLM harness replaces stream_response so every behavior can be
  asserted without a network call, an API key, or model flakiness.

  Scenario: the full suite runs with no network via ScriptedLLM
    Given agent.stream_response is monkeypatched with a ScriptedLLM instance
    And no ANTHROPIC_API_KEY is set in the environment
    When uv run pytest tests/test_agent.py tests/test_tools.py -q runs
    Then all tests pass (17 or more) without any network connection
    And the run completes in under 5 seconds

  Scenario: a scripted plain-text turn asserts the stop condition
    Given a ScriptedLLM scripted with one turn: [_chunk(content="Hello, "), _chunk(content="world."), _chunk(finish_reason="stop")]
    When run_agent("say hi") is called with that ScriptedLLM patched in
    Then messages[1]["role"] equals "assistant"
    And messages[1]["content"] equals "Hello, world."
    And no message in the history has role "tool"
    And the loop made exactly 1 call to stream_response

  Scenario: a scripted tool turn asserts the role-tool result threading
    Given a ScriptedLLM scripted with turn 1 emitting a list_dir call with id "call_1" and turn 2 returning "Found marker.txt."
    And a temp directory containing "marker.txt"
    When run_agent("list the dir") is called with that ScriptedLLM patched in
    Then messages[2]["role"] equals "tool"
    And messages[2]["tool_call_id"] equals "call_1"
    And messages[2]["content"] contains "marker.txt"
    And messages[-1]["content"] equals "Found marker.txt."

  Scenario: every other phase gate runs on this same ScriptedLLM harness
    Given the ScriptedLLM, _chunk, and _tc helpers defined in tests/test_agent.py
    When any BDD scenario from Phase 6, 7, 8, or 11 is executed
    Then it monkeypatches agent.stream_response (not provider.stream_response)
    And it uses the same _chunk/_tc builders to construct streaming turns
    And it asserts on run_agent's returned messages list without touching the network
```

## Notes / open questions

- Monkeypatch `agent.stream_response`, NOT `provider.stream_response`. By the time the test runs, `agent.py` has already bound its own local reference from the `from provider import stream_response` import; patching the source module has no effect.
- `ScriptedLLM.pop(0)` raises `IndexError` if the loop makes more `stream_response` calls than scripted turns — this is the intended failure signal, not a silent pass.
- The `test_tool_call_then_stop` test deliberately splits `list_dir` arguments across two chunks to exercise the accumulation buffer; both fragments must be concatenated before `json.loads`.
- `pyproject.toml` must have `pythonpath = ["src"]` under `[tool.pytest.ini_options]` for `import agent` to work without a full package install — check this if tests fail with `ModuleNotFoundError`.
- Phase 9's harness is the BDD foundation: all other phases' BDD scenarios use the same `ScriptedLLM`, `_chunk`, and `_tc` helpers via a shared `conftest.py` fixture.

---

**Tutorial build step 9 of 32** · ← [Phase 8 — System Prompt & CLI](./phase-08-system-prompt-and-cli.md) · [Phase 10.1 — The `emit()` Seam](./phase-10-1-event-seam.md) →
