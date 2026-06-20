Status: not started

# Phase 10.2 — The Transcript Pane

## Goal

Build a minimal Textual app with a single scrollable `TranscriptPane` widget and wire it to the `emit()` seam via `AGENT_UI=tui`, so streamed `text_delta` events appear in the terminal UI in real time while the stdout path remains unchanged.

## Files changed

| File | Change |
|---|---|
| `src/tui/__init__.py` | **New.** TUI entry point; exports `run(task)` which creates `AgentApp`, calls `set_app`, and blocks on `app.run()`. |
| `src/tui/components/__init__.py` | **New.** Empty package marker for the components sub-package. |
| `src/tui/components/transcript.py` | **New.** `TranscriptPane(RichLog)` widget; `append_text(delta)` appends a streamed fragment with `scroll_end=True`. |
| `src/tui/app.py` | **New.** `AgentApp(App)` with a single `TranscriptPane`. `on_mount` creates a `run_agent` asyncio Task. `handle_agent_event` routes `text_delta` to `TranscriptPane.append_text`. |
| `src/tui/emit.py` | **New.** Module-level `_app` ref; `set_app(app)` registers the live instance; `emit(event)` calls `app.handle_agent_event(event)`. |
| `src/renderer.py` | Update the `tui` branch import from a `# noqa` stub to the real `from tui.emit import emit`. |
| `main.py` | Add `AGENT_UI` dispatch: `tui` → `from tui import run; run(task)`; else → `asyncio.run(run_agent(task))`. |
| `tests/test_transcript_pane.py` | **New.** BDD integration test using Textual's `Pilot`; asserts `TranscriptPane` contains expected text after a scripted agent run. |

## Order of operations

1. Install Textual: `uv add textual`.
2. Create `src/tui/` package directories and empty `__init__.py` / `components/__init__.py` stubs.
3. Write `src/tui/components/transcript.py` (`TranscriptPane` with `append_text`); write a unit test that calls `append_text` and checks `RichLog` content via `Pilot` — run red.
4. Write `src/tui/emit.py` (`set_app` + `emit`).
5. Write `src/tui/app.py` (`AgentApp`): `compose` mounts `TranscriptPane`; `on_mount` creates the agent task; `handle_agent_event` routes `text_delta`.
6. Write `src/tui/__init__.py` (`run` function).
7. Update `src/renderer.py` so the `tui` branch resolves to `from tui.emit import emit` (was a comment stub).
8. Update `main.py` with the `AGENT_UI` dispatch block.
9. Run the BDD test green; run `uv run pytest -q` → 17 passed.

## Verification

- [ ] Tests added/updated: `tests/test_transcript_pane.py`
- [ ] All pre-existing tests still pass: `uv run pytest -q` → 17 passed (plus new tests)
- [ ] TUI launch:
  ```bash
  AGENT_UI=tui uv run main.py "explain what the agent loop does in one sentence"
  ```
  Full-screen Textual app appears; text streams into the pane; press `q` or `Ctrl-C` to exit.
- [ ] Stdout path unchanged:
  ```bash
  uv run main.py "explain what the agent loop does in one sentence"
  ```
- [ ] BDD acceptance:

```gherkin
Scenario: TUI transcript pane renders streamed text
  Given the agent is launched with AGENT_UI=tui
  When the agent processes a task that produces streamed text
  Then text_delta events are routed to the TranscriptPane widget
  And the text visible in the transcript pane is identical to the
      assistant content that would appear in a stdout run
  And the final message history contains the same messages as a stdout run
```

## Notes / open questions

- `AgentApp.on_mount` imports `run_agent` inside the method (not at module top) to avoid a circular dependency: `agent` imports `renderer`, `renderer` imports `tui.emit`, `tui.emit` is set up before `run_agent` starts.
- `RichLog` with `scroll_end=True` pins the viewport to the bottom on every write; Textual automatically suspends the pin when the user scrolls up manually.
- Tool call events (`tool_call_start`, `tool_call_end`) arrive during this layer but are silently ignored in `handle_agent_event` — they will be wired in Layer 10.3.
- Textual's `Pilot` test harness (`app.run_async()` in test mode) allows asserting widget state without a real terminal; use `ScriptedLLM` from the Phase 9 test harness to drive the agent.

---

**Tutorial build step 11 of 32** · ← [Phase 10.1 — The `emit()` Seam](./phase-10-1-event-seam.md) · [Phase 10.3 — The Tool Panel](./phase-10-3-tool-panel.md) →
