Status: done
Branch: step/phase-10-1-event-seam

# Phase 10.1 — The `emit()` Seam

## Goal

Refactor every `print()` call in `agent.py` into a typed `emit(event)` call dispatched through a renderer module, shipping a `StdoutRenderer` that reproduces the original output byte-for-byte so the change is invisible to existing callers.

## Files changed

| File | Change |
|---|---|
| `src/renderer_stdout.py` | **New.** Default renderer; handles `text_delta`, `tool_call_start`, `tool_call_end`, `turn_end`, `agent_end` events and prints exactly what the old `print()` calls produced. |
| `src/renderer.py` | **New.** Selector module; reads `AGENT_UI` env var at import time and re-exports the matching `emit`. `tui` → `tui.emit.emit`; anything else → `renderer_stdout.emit`. |
| `src/agent.py` | Replace the five `print()` calls with `emit(event)` calls. Add `from renderer import emit`. Include `"index"` in `parsed_calls` dicts. Emit `tool_call_end` on error paths. Emit `agent_end` before `return messages`. |
| `tests/test_event_seam.py` | **New.** BDD integration test: run agent with `AGENT_UI=stdout` on a scripted task; assert captured stdout is identical to pre-refactor baseline. |

## Order of operations

1. Write `src/renderer_stdout.py` with all five event-type branches; run the existing 17-test suite and confirm it still passes (no imports of the new module yet — this is a sanity baseline).
2. Write `src/renderer.py` with the `AGENT_UI` selector; confirm `from renderer import emit` works with `AGENT_UI=stdout`.
3. Add `from renderer import emit` to `src/agent.py`; replace `print(delta.content, ...)` with `emit({"type": "text_delta", ...})`.
4. Replace the `tool_call_start` print (`▸ {fn.name}`) with `emit({"type": "tool_call_start", ...})`.
5. Replace the two status prints in `_execute_one_tool` (success and error branches) with `emit({"type": "tool_call_end", ...})`; add `"index"` field to `parsed_calls` dicts in `_execute_tools_parallel`.
6. Replace the `print()` after the streaming loop with `emit({"type": "turn_end", ...})`.
7. Add `emit({"type": "agent_end", ...})` just before `return messages`.
8. Write the BDD test in `tests/test_event_seam.py`; run it red (before step 1 was done it would fail; at this point it should go green).
9. Run `uv run pytest -q` — must show 17+ passed.

## Verification

- [ ] Tests added/updated: `tests/test_event_seam.py`
- [ ] All pre-existing tests still pass: `uv run pytest -q` → 17 passed (plus new test)
- [ ] CLI run (default / explicit stdout):
  ```bash
  uv run main.py "list the files in the current directory"
  AGENT_UI=stdout uv run main.py "list the files in the current directory"
  ```
  Output must be byte-for-byte identical to the Phase 9 baseline.
- [ ] BDD acceptance (paste as gherkin scenario into test suite):

```gherkin
Scenario: StdoutRenderer output is identical to the original print() output
  Given the agent is run with AGENT_UI=stdout (the default)
  When the agent processes a task that produces streamed text and one tool call
  Then the captured stdout is byte-for-byte identical to the output produced
       by the same task before the emit() refactor
  And the final message history contains the same assistant and tool messages
```

## Notes / open questions

- The `emit()` seam is the single architectural boundary that makes every subsequent UI layer possible (ADR-0009). The loop must never call `print` again after this layer.
- `renderer.py` resolves `AGENT_UI` once at import time — hot-swapping renderers mid-run is intentionally not supported.
- The `tui` branch in `renderer.py` imports `tui.emit` which does not exist yet; it will raise `ImportError` until Layer 10.2. This is expected — `AGENT_UI=tui` is not runnable until then.
- If any Phase 9 test monkeypatches `print` directly in `agent`, update it to capture `renderer.emit` calls instead.
- `_execute_one_tool`'s unknown-tool error path must also emit `tool_call_end` with `is_error=True`, `chars=0`.

---

**Tutorial build step 10 of 32** · ← [Phase 9 — Testing the Agent](./phase-09-testing-the-agent.md) · [Phase 10.2 — The Transcript Pane](./phase-10-2-transcript.md) →
