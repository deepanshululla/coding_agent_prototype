Status: not started

# Phase 1 — Talk to a Model

## Goal

Create `src/provider.py` with a `ModelClient` class that shells out to `claude -p` via `asyncio.create_subprocess_exec`, and expose a stable module-level `call_model` function that the rest of the tutorial imports — no API key required.

## Files changed

| File | Change |
|---|---|
| `src/provider.py` | New file: `ModelClient` class with `async def complete(...)`, module singleton `_client`, and `call_model` delegating to it |
| `tests/test_provider.py` | New file: two async tests monkeypatching `ModelClient.complete` to verify delegation and argument forwarding |
| `pyproject.toml` | Add `[tool.pytest.ini_options]` with `pythonpath = ["src"]` and `asyncio_mode = "auto"` |

## Order of operations

1. Add `[tool.pytest.ini_options]` to `pyproject.toml` and install dev deps: `uv add --dev pytest pytest-asyncio`.
2. Write `tests/test_provider.py` with `test_call_model_returns_text` and `test_call_model_passes_latest_message`. Run and confirm `ModuleNotFoundError`.
3. Create `src/provider.py`: define `MODEL_ALIAS`, `ModelClient.complete` (subprocess logic), `_client` singleton, and `call_model`.
4. Run the tests again — both should pass.
5. Optionally run `scratch_phase1.py` at the repo root to verify the round-trip against the live CLI.

## Verification

- [ ] Tests added: `tests/test_provider.py`
- [ ] Run: `uv run pytest tests/test_provider.py -v` — expect `2 passed`
- [ ] Live smoke test: `uv run python scratch_phase1.py` — model returns a five-word reply
- [ ] BDD gate (red before, green after):

```gherkin
Feature: Talking to the model
  call_model sends a message to the model backend and returns the reply text.
  The function is the stable interface for all later phases; the class and
  subprocess details are implementation details hidden behind it.

  Scenario: A user message returns the model's text reply
    Given a mocked ModelClient.complete that returns "hi there"
    When call_model is invoked with messages=[{"role":"user","content":"say hi"}]
    And system_prompt is "You are a helpful assistant."
    Then the return value is exactly "hi there"
    And no subprocess is spawned during the call

  Scenario: The system prompt is forwarded to the backend intact
    Given a capturing ModelClient.complete that records its arguments
    When call_model is invoked with any user message and system_prompt "Be brief."
    Then the captured system_prompt equals "Be brief."
    And the captured messages list ends with the user message that was passed in

  Scenario: An empty string reply from the model does not raise
    Given a mocked ModelClient.complete that returns ""
    When call_model is invoked with a user message
    Then the return value is "" and no exception is raised
    And the caller receives an empty string it can check before displaying
```

## Notes / open questions

- The `claude -p` backend is text-only in this phase (`--output-format text`). LiteLLM replaces it in Phase 11; `call_model`'s signature is intentionally kept stable to make that swap zero-cost outside `provider.py`.
- `MODEL_ALIAS = "sonnet"` is a module constant; change to `"opus"` etc. as needed during development.
- `scratch_phase1.py` is a throwaway verification script — do not commit it; `tests/test_provider.py` is the lasting artifact.

---

**Tutorial build step 1 of 32** · _(first step)_ · [Phase 2 — The Conversation Loop](./phase-02-the-agent-loop.md) →
