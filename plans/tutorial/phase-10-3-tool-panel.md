Status: done
Branch: step/phase-10-3-tool-panel

# Phase 10.3 — The Tool Panel

## Goal

Add a `ToolPanel` widget alongside the transcript pane that shows each tool call as a live spinner row on `tool_call_start` and resolves it to ✓ or ✗ with a char count on `tool_call_end`, with no changes to `agent.py` or `renderer.py`.

## Files changed

| File | Change |
|---|---|
| `src/tui/components/tool_panel.py` | **New.** `ToolPanel(DataTable)` with `add_tool_row(index, name)` and `finish_tool_row(index, ok, chars)`. Tracks in-flight rows via `_rows: dict[int, _ToolRow]`. `clear_rows()` resets the panel between turns. |
| `src/tui/app.py` | Update `AgentApp`: add `Horizontal` container, mount `ToolPanel` alongside `TranscriptPane`, wire `tool_call_start` → `panel.add_tool_row` and `tool_call_end` → `panel.finish_tool_row` in `handle_agent_event`. |
| `tests/test_tool_panel.py` | **New.** BDD integration test using `Pilot`; asserts `ToolPanel` row count and cell values after scripted tool call events. |

## Order of operations

1. Write `src/tui/components/tool_panel.py`: define `_ToolRow` dataclass, `ToolPanel(DataTable)` with three columns (`icon`, `name`, `detail`), `add_tool_row`, `finish_tool_row`, and `clear_rows`. Write a unit test that drives these methods and checks `row_count` and cell content — run red.
2. Make the unit test green by completing the implementation.
3. Update `src/tui/app.py`:
   - Import `Horizontal` from `textual.containers` and `ToolPanel` from `tui.components.tool_panel`.
   - Change `compose` to wrap both widgets in `Horizontal`.
   - Add CSS for `Horizontal { height: 1fr; }`.
   - Extend `handle_agent_event` to handle `tool_call_start` and `tool_call_end`.
4. Write the BDD integration test in `tests/test_tool_panel.py`; run it red, then green.
5. Run `uv run pytest -q` → 17+ passed.

## Verification

- [ ] Tests added/updated: `tests/test_tool_panel.py`
- [ ] All pre-existing tests still pass: `uv run pytest -q` → 17 passed (plus new tests)
- [ ] TUI launch with a tool-calling task:
  ```bash
  AGENT_UI=tui uv run main.py "read the file src/agent.py and summarise it"
  ```
  Transcript on left streams model text; tool panel on right shows `⏳ read_file`, which resolves to `✓ read_file  N,NNNc`.
- [ ] Parallel tool calls (Phase 7-style task) produce multiple rows that resolve independently.
- [ ] BDD acceptance:

```gherkin
Scenario: Tool panel shows spinner and resolves on completion
  Given the agent is launched with AGENT_UI=tui
  When the agent executes a tool call during a run
  Then a row appears in the ToolPanel with a spinner icon when tool_call_start fires
  And the row's icon changes to ✓ and shows a char count when tool_call_end fires with is_error=False
  And the row's icon changes to ✗ when tool_call_end fires with is_error=True
```

## Notes / open questions

- No changes to `agent.py` or `renderer.py` are needed: `tool_call_start` and `tool_call_end` events were already emitted in Layer 10.1 and silently ignored in Layer 10.2's `handle_agent_event`.
- Panel-clearing strategy: clearing on every `turn_end` removes results before the user can read them. Preferred heuristic: clear when the first `tool_call_start` of a new turn arrives (natural reset). A short delay on `turn_end` is also acceptable. Defer the decision unless it causes a visible UX problem.
- `ToolPanel` uses `show_header=False, show_cursor=False` to keep the display read-only and compact.
- The `update_cell(key, column_key, value)` API requires that the row `key` (passed as `str(index)` to `add_row`) and column labels (`"icon"`, `"name"`, `"detail"`) match exactly.
- Use the `ScriptedLLM` fixture from Phase 9's test harness inside `Pilot` to produce deterministic `tool_call_start` / `tool_call_end` events for the BDD test.

---

**Tutorial build step 12 of 32** · ← [Phase 10.2 — The Transcript Pane](./phase-10-2-transcript.md) · [Phase 10.4 — Input & Status Bar](./phase-10-4-input-status.md) →
