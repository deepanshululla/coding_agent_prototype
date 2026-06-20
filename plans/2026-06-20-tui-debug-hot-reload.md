# TUI Hot Reload

**Status:** done  
**Created:** 2026-06-20

## Goal

Add hot reload support to the TUI that automatically restarts the application when source code changes are detected, enabling rapid iteration during TUI development without manual restarts.

## Context

Currently, developing TUI components requires:
1. Make a code change
2. Exit the TUI (ctrl+q)
3. Restart the application
4. Navigate back to the state you were testing

This cycle is slow and breaks flow. A hot reload mode would preserve state where possible and restart the TUI automatically on file changes.

## Design decisions

### 1. File watching strategy

Use `watchfiles` library (async, battle-tested, used by uvicorn/fastapi):
- Watch `src/tui/**/*.py` by default
- Debounce: 200ms window to catch bulk saves
- Ignore `__pycache__`, `.pyc`, `.pytest_cache`

**Why watchfiles over alternatives:**
- `watchdog`: thread-based, hard to integrate with asyncio
- Manual polling: wasteful, slow to respond
- `inotify`/`kqueue` raw: platform-specific boilerplate

### 2. Reload mechanism

Two approaches considered:

**A) Process restart (chosen):**
- Pros: Clean slate, no module-reload bugs, simple state preservation via pickle
- Cons: Slower restart (~500ms), loses uncommitted agent state
- Implementation: `os.execv(sys.executable, [sys.executable] + sys.argv)` after cleanup

**B) Module reload (rejected):**
- Pros: Faster, can preserve full agent state
- Cons: Fragile (cached classes, circular imports, event loop conflicts), textual doesn't handle mid-run widget replacement well
- Risk: Silent bugs from stale references

**Choice:** Process restart with state preservation. Speed hit is acceptable for debug mode.

### 3. State preservation

Preserve across restarts:
- Current transcript content (serialized text)
- Tool panel state (tool call history)
- Input box history (last N submissions)
- Agent task (the original prompt)

**Not preserved:**
- Agent history mid-turn (too complex, debug mode is for UI work not agent logic)
- Steering queue (reset is clean)

Serialize to `/tmp/tui-debug-state-{pid}.json` before restart, load on mount if present.

### 4. Activation

Enable via environment variable:
```bash
AGENT_HOT_RELOAD=1 uv run main.py "your task"
```

Or CLI flag:
```bash
uv run main.py --hot-reload "your task"
```

**Why not always-on:**
- Adds watchfiles dependency overhead
- Unnecessary in production use
- Clear signal that behavior is different

### 5. User feedback

When reload triggers:
- Flash status bar: `[HOT RELOAD] Reloading...` (yellow background, 100ms)
- Log to transcript: `\n[hot-reload] Code changed, reloading...\n` before shutdown
- On restart: `\n[hot-reload] Reloaded at HH:MM:SS\n`

## Implementation plan

### File changes table

| File | Change | Reason |
|------|--------|--------|
| `pyproject.toml` | Add `watchfiles>=0.24.0` to dependencies | File watching library |
| `main.py` | Add `--hot-reload` flag extraction | CLI activation |
| `src/tui/app.py` | Add `_hot_reload: bool` field, state save/load methods | Core reload logic |
| `src/tui/app.py` | Add `_start_file_watcher()` task in `on_mount` | Launch watcher when hot reload enabled |
| `src/tui/app.py` | Add `_handle_reload()` method | Serialize state, log, exec restart |
| `src/tui/hot_reload.py` (new) | File watcher coroutine, state serialization helpers | Hot reload infrastructure |
| `tests/test_hot_reload.py` (new) | Test state serialization, watcher debounce, flag parsing | TDD coverage |

### Order of implementation

1. **Add `--hot-reload` flag parsing in `main.py`**
   - Extract flag similar to `--model`, `--dir`
   - Pass to `AgentApp.__init__` as `hot_reload=True`
   - Test: `--hot-reload` sets flag, passes through to app

2. **Add state serialization in `src/tui/hot_reload.py`**
   - `save_tui_state(app: AgentApp) -> Path`: extract transcript, tool panel, task
   - `load_tui_state() -> dict | None`: read from `/tmp/tui-hot-reload-state-*.json`
   - Schema: `{task, transcript_lines, tool_rows, timestamp}`
   - Test: round-trip serialization, missing file returns None

3. **Add state restore in `AgentApp.on_mount`**
   - If hot reload enabled and state file exists: restore transcript, tool panel
   - Append `[hot-reload] Reloaded at ...` line
   - Clean up state file after load
   - Test: mock state file, verify widgets populated

4. **Add file watcher in `src/tui/hot_reload.py`**
   - `watch_tui_files(app: AgentApp)`: async loop with watchfiles
   - Watch `src/tui/**/*.py`, debounce 200ms
   - On change: call `app.trigger_reload()`
   - Test: mock file change, verify callback fires

5. **Add reload trigger in `AgentApp`**
   - `trigger_reload()`: save state, log to transcript, call `_do_reload()`
   - `_do_reload()`: `os.execv(sys.executable, sys.argv)`
   - Flash status bar before exec
   - Test: verify state saved, execv called with correct args

6. **Wire watcher into `AgentApp.on_mount`**
   - If `self._hot_reload`: `asyncio.create_task(watch_tui_files(self))`
   - Test: end-to-end with real file write, verify reload

### Tests to write (before each step)

1. `test_hot_reload_flag_parsing`: `--hot-reload` sets flag, missing flag defaults False
2. `test_state_serialization`: save/load round-trip, handles missing widgets
3. `test_state_restore_on_mount`: mock state file, verify transcript populated
4. `test_file_watcher_debounce`: rapid changes trigger single reload
5. `test_reload_preserves_task`: original task persists across restart
6. `test_hot_reload_disabled_by_default`: no watcher when flag absent

## Edge cases

- **Watcher triggers during agent turn:** Save mid-turn state, warn in transcript that agent was interrupted
- **Syntax error in changed file:** Reload will crash; pytest pre-commit hook should catch this, but log clearly if it happens
- **Multiple TUI instances running:** PID in state filename prevents collision
- **State file from previous crash:** Stale state has timestamp; ignore if >1 hour old
- **Reload loop (file saves itself):** Only watch `src/tui/`, not temp dirs or logs

## Future enhancements (out of scope)

- **Selective reload:** Only restart on changes to specific files (e.g., skip reload on comment changes)
- **State preservation for agent history:** Pickle full conversation state (complex, fragile)
- **Live CSS reload:** Textual supports `app.refresh_css()` without restart — could fast-path style-only changes
- **Config file for watch paths:** Let users extend watched directories via `.debug.yaml`

## How to verify

After implementation:

1. Start TUI with `AGENT_HOT_RELOAD=1 uv run main.py "test task"`
2. Edit `src/tui/components/transcript.py` (e.g., change a color)
3. Save the file
4. Within 200ms, TUI should flash "Reloading..." and restart
5. Transcript should preserve previous content + show `[hot-reload] Reloaded at ...`
6. Original task should still be running

## Dependencies

- `watchfiles>=0.24.0` (async file watcher, ~10ms overhead)
- No changes to textual required (restart is out-of-band)

## Rollout

- Merge behind `--hot-reload` flag (off by default)
- Document in README under "Development" section
- Add to CLAUDE.md as "use `--hot-reload` when iterating on TUI components"
