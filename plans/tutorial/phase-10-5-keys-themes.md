Status: done
Branch: step/phase-10-5-keys-themes

# Phase 10.5 — Keybindings & Themes

## Goal

Add Vim-style modal keybindings (NORMAL / INSERT / COMMAND modes), cooperative `Ctrl-C` cancel via an `asyncio.Event`, and `AGENT_THEME`-driven semantic color schemes to turn the four-region TUI into a fully usable tool, without changing the agent loop beyond two backward-compatible parameter additions.

## Files changed

| File | Change |
|---|---|
| `src/tui/themes.py` | **New.** `THEMES` dict mapping `"dark"` / `"light"` / `"high_contrast"` to semantic color role dicts. `get_theme(name)` returns the dict with a `"dark"` fallback and a stderr warning on unknown names. |
| `src/tui/app.py` | Add `mode: reactive[str]` (`"normal"` / `"insert"` / `"command"`). Add `BINDINGS` list for `j`, `k`, `g,g`, `G`, `i`, `colon`, `escape`, `ctrl+c`. Implement `check_action` to gate scroll actions to NORMAL mode. Add action methods: `action_scroll_down/up/top/bottom`, `action_enter_insert/command/normal`, `action_cancel_turn`. Add `cancel_event: asyncio.Event` to `__init__`. Pass `cancel_event` to `run_agent` in `on_mount`. Read `AGENT_THEME` and call `get_theme`; pass `theme` to each widget. Wire `agent_cancelled` event in `handle_agent_event` → `status.set_cancelled()`. Update `on_input_box_submitted` to call `action_enter_normal()` after submit. |
| `src/tui/components/tool_panel.py` | Accept `theme: dict[str, str] | None = None` in `__init__`; store as `self._theme`. Use `self._theme.get("tool_ok")` / `"tool_error"` in `finish_tool_row` instead of hardcoded color strings. |
| `src/tui/components/status_bar.py` | Accept `theme: dict[str, str] | None = None` in `__init__`; store `self._color = theme.get("status", "grey70")`. Apply that color in `_render` via `Rich.Text`. |
| `src/tui/components/transcript.py` | Accept `theme: dict[str, str] | None = None` in `__init__`; use `theme["user"]` color when echoing the `> ` prefix for user messages (assistant text remains unstyled). |
| `src/agent.py` | Add optional `cancel_event: asyncio.Event | None = None` to `run_agent`. At the top of each inner-loop pass, check `cancel_event.is_set()`; if set, clear it, emit `{"type": "agent_cancelled"}`, and break out of the inner loop. |
| `tests/test_keys_themes.py` | **New.** BDD integration test: assert mode transitions via `Pilot` key presses; assert theme color roles appear on widgets; assert `cancel_event` stops the inner loop and emits `agent_cancelled`. |

## Order of operations

1. Write `src/tui/themes.py` with all three theme dicts and `get_theme`; write a unit test that verifies `get_theme("dark")["tool_ok"] == "bright_green"` and `get_theme("unknown")` returns the dark fallback — run red, then green.
2. Update `src/agent.py`: add `cancel_event: asyncio.Event | None = None` to `run_agent`; add the cooperative-cancel check at the top of the inner loop; emit `agent_cancelled`. Run `uv run pytest -q` → 17 passed (all existing callers pass `None` implicitly).
3. Update each widget (`ToolPanel`, `StatusBar`, `TranscriptPane`) to accept and use the `theme` dict — replace hardcoded color strings with theme role lookups. Run existing widget unit tests green.
4. Update `src/tui/app.py`:
   - Add `mode` reactive and `BINDINGS` list.
   - Implement `check_action` to block scroll actions in INSERT mode.
   - Add all action methods.
   - Add `cancel_event = asyncio.Event()` in `__init__`.
   - Read `AGENT_THEME` env var and call `get_theme`; pass to widgets in `compose`.
   - Pass `cancel_event` to `run_agent` in `on_mount`.
   - Add `agent_cancelled` branch in `handle_agent_event`.
   - Call `action_enter_normal()` at end of `on_input_box_submitted`.
5. Write and run the BDD test green.
6. Run `uv run pytest -q` → 17 passed (plus new tests).
7. Smoke-test all three themes manually.

## Verification

- [ ] Tests added/updated: `tests/test_keys_themes.py`
- [ ] Regression: `uv run pytest -q` → 17 passed (`cancel_event=None` default preserves all Phase 9 tests)
- [ ] TUI runs with all three themes:
  ```bash
  AGENT_UI=tui uv run main.py "read src/agent.py and list the public functions"
  AGENT_UI=tui AGENT_THEME=light uv run main.py "read src/agent.py and list the public functions"
  AGENT_UI=tui AGENT_THEME=high_contrast uv run main.py "read src/agent.py and list the public functions"
  ```
- [ ] Key behavior: app starts in NORMAL mode; `j`/`k` scroll transcript; `i` focuses input box (INSERT mode); Enter submits and returns to NORMAL; `Ctrl-C` during streaming → status bar shows `cancelled`, process stays alive; `:q` in COMMAND mode quits cleanly.
- [ ] BDD acceptance:

```gherkin
Scenario: Vim-style modal keybindings and theme env var changes colors
  Given the agent is launched with AGENT_UI=tui and the app starts in NORMAL mode
  When the user presses `j` then `k`
  Then the transcript scrolls down then up
  And pressing `i` switches to INSERT mode and focuses the input box
  And typing a follow-up message then pressing Enter queues a steering message and returns to NORMAL mode
  And pressing Ctrl-C during a run cancels the in-flight turn and the status bar shows "cancelled"
  And setting AGENT_THEME=light changes the ToolPanel "tool_ok" color to the light theme value
  And setting AGENT_THEME=light changes the StatusBar "status" color to the light theme value
```

## Notes / open questions

- This is an additive delta over Layer 10.4 — `renderer.py`, `renderer_stdout.py`, and `main.py` are not touched.
- COMMAND mode (`:q`) is implemented as a simple prefix check: when mode is `"command"` and the command buffer is `"q"`, call `self.exit()`. Full ex-command parsing is out of scope for this layer.
- `check_action` gates scroll motions (`scroll_down`, `scroll_up`, `scroll_top`, `scroll_bottom`) to NORMAL mode only; INSERT must not consume `j`/`k` so they can be typed freely in the input box.
- The `cancel_event.is_set()` check fires at the top of each iteration, not mid-stream. This means one streaming response may complete before the cancel takes effect — that is intentional (cooperative, not preemptive).
- `AGENT_THEME` is read once at `AgentApp.__init__` time; live theme switching is out of scope.
- Vim-modal keybindings are a known divergence from Textual's default focus-based input model; document the design rationale in a follow-up note in `plans/` if the implementation reveals edge cases (e.g., `g,g` chord timing).

---

**Tutorial build step 14 of 32** · ← [Phase 10.4 — Input & Status Bar](./phase-10-4-input-status.md) · [Phase 11 — Add LiteLLM (Multi-Provider)](./phase-11-add-litellm.md) →
