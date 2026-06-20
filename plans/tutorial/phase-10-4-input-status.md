Status: not started

# Phase 10.4 — Input & Status Bar

## Goal

Complete the four-region TUI layout by adding an `InputBox` for submitting tasks and a `StatusBar` that shows the model name, iteration counter, and elapsed time, wiring both to the existing event stream and threading `pending_messages` through `run_agent` so future steering messages can be injected from the UI.

## Files changed

| File | Change |
|---|---|
| `src/tui/components/status_bar.py` | **New.** `StatusBar(Static)` pinned to one line; `set_iteration(n)`, `set_done(total)`, `set_cancelled()` update a formatted label. Reads `AGENT_MODEL` env var. |
| `src/tui/components/input_box.py` | **New.** `InputBox(Input)` with an inner `Submitted(Message)` class; posts the message on Enter and clears itself. |
| `src/tui/app.py` | Update `AgentApp.__init__` to accept `pending_messages: list[dict]`. Mount `InputBox` and `StatusBar` in `compose`. Add `on_input_box_submitted` handler. Wire `turn_end` → `status.set_iteration` and `agent_end` → `status.set_done` in `handle_agent_event`. Pass `pending_messages` to `run_agent` in `on_mount`. |
| `src/tui/__init__.py` | Update `run(task)` to create the shared `pending: list[dict]` and pass it to both `AgentApp` and (via the app) `run_agent`. |
| `src/agent.py` | Add optional `pending_messages: list[dict] | None = None` parameter to `run_agent`; skip the local `pending_messages = []` init when the arg is provided. All existing callers continue to work unchanged. |
| `tests/test_input_status.py` | **New.** BDD integration test; asserts status bar text after `turn_end` and `agent_end` events; asserts `pending_messages` is populated after `InputBox.Submitted`. |

## Order of operations

1. Write `src/tui/components/status_bar.py` with all three update methods and `_render`; write a unit test that calls `set_iteration(3)` and checks the rendered string contains `"iter 3/30"` — run red, then green.
2. Write `src/tui/components/input_box.py` with the `Submitted` message; write a `Pilot` test that simulates pressing Enter and asserts `Submitted` was posted — run red, then green.
3. Update `src/agent.py`: change `run_agent` signature to accept `pending_messages: list[dict] | None = None`; guard the local init with `if pending_messages is None: pending_messages = []`. Run `uv run pytest -q` → 17 passed (backward compat check).
4. Update `src/tui/app.py`:
   - Add `pending_messages` to `__init__` and store as `self._pending`.
   - Add imports for `InputBox` and `StatusBar`.
   - Update `compose` to yield `InputBox` and `StatusBar` below the `Horizontal`.
   - Add `on_input_box_submitted`: append to `self._pending`, echo in transcript.
   - Wire `turn_end` and `agent_end` in `handle_agent_event`.
   - Pass `self._pending` to `run_agent` in `on_mount`.
5. Update `src/tui/__init__.py` to create `pending: list[dict] = []` and pass it to `AgentApp`.
6. Write and run the BDD test green.
7. Run `uv run pytest -q` → 17 passed (plus new tests).

## Verification

- [ ] Tests added/updated: `tests/test_input_status.py`
- [ ] Regression: `uv run pytest -q` → 17 passed (the `pending_messages=None` default must preserve all Phase 9 tests)
- [ ] TUI launch showing all four regions:
  ```bash
  AGENT_UI=tui uv run main.py "list the Python files in src/"
  ```
  Expected layout:
  ```
  ┌─────────────────────────────────┬──────────────────────┐
  │  TranscriptPane                 │  ToolPanel           │
  │  (streaming model text)         │  ⏳ list_dir         │
  │                                 │  ✓ list_dir  42c     │
  ├─────────────────────────────────┴──────────────────────┤
  │  Type a task and press Enter…                          │
  ├────────────────────────────────────────────────────────┤
  │  claude-sonnet-4-5  •  iter 2/30  •  8s               │
  └────────────────────────────────────────────────────────┘
  ```
  Status bar advances iteration counter on each `turn_end`; shows `done (N iters)` on `agent_end`.
- [ ] BDD acceptance:

```gherkin
Scenario: Input box starts a run and status bar tracks iterations
  Given the agent is launched with AGENT_UI=tui
  When the user types a task into the input box and presses Enter
  Then the task text is pushed into pending_messages
  And run_agent begins a new inner-loop pass with that task
  And the status bar shows "iter N/30" after each turn_end event fires
  And the status bar shows "done" after the agent_end event fires
```

## Notes / open questions

- `pending_messages` is passed by reference from `tui/__init__.py` through `AgentApp` to `run_agent`. The outer loop already reads from and clears this list on each inner-loop pass; no protocol change is needed.
- The `InputBox.Submitted` inner message class follows Textual's component message convention; `AgentApp.on_input_box_submitted` is auto-wired by Textual's naming convention.
- This layer foreshadows Phase 15 steering: the infrastructure for follow-up messages is in place; the outer loop is not yet started here (it needs a dedicated steering phase to handle multi-turn input safely).
- `StatusBar` reads `AGENT_MODEL` from the environment at `__init__` time for display purposes only; no model selection logic is added here.
- Empty `InputBox` submissions (whitespace-only) are filtered out in `on_input_submitted` before posting the message.

---

**Tutorial build step 13 of 32** · ← [Phase 10.3 — The Tool Panel](./phase-10-3-tool-panel.md) · [Phase 10.5 — Keybindings & Themes](./phase-10-5-keys-themes.md) →
