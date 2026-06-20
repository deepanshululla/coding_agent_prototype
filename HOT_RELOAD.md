# TUI Hot Reload

The TUI now supports hot reload mode for rapid development iteration. When enabled, the application automatically restarts when source files change, preserving your session state.

## Usage

Enable hot reload with either:

**Environment variable:**
```bash
AGENT_UI=tui AGENT_HOT_RELOAD=1 uv run main.py "your task"
```

**Command-line flag:**
```bash
AGENT_UI=tui uv run main.py --hot-reload "your task"
```

## How it works

1. **File watching**: Monitors `src/tui/**/*.py` for changes with 200ms debounce
2. **State preservation**: Saves transcript content and original task to `/tmp/tui-hot-reload-state-{pid}.json`
3. **Process restart**: Uses `os.execv` for clean restart (not module reload)
4. **State restoration**: Loads saved state on startup, appends reload timestamp

## What's preserved

- ✅ Transcript content
- ✅ Original task
- ✅ Reload timestamp

## What's NOT preserved

- ❌ Agent conversation history (mid-turn state)
- ❌ Steering queue
- ❌ Tool panel state

## Visual feedback

When a reload triggers:
```
[hot-reload] Reloading at 14:30:45...
```

After restart:
```
[hot-reload] Reloaded at 14:30:46
```

## Implementation

### Files added
- `src/tui/hot_reload.py` - State serialization and file watching
- `tests/test_hot_reload.py` - Test coverage

### Files modified
- `main.py` - Flag parsing (`--hot-reload`, `AGENT_HOT_RELOAD`)
- `src/tui/__init__.py` - Accept hot_reload parameter
- `src/tui/app.py` - State save/restore, file watcher, reload trigger
- `src/tui/components/transcript.py` - Add `get_text()` for state extraction
- `pyproject.toml` - Add `watchfiles>=0.24.0` dependency

### Key functions

**State management:**
- `save_tui_state(app)` - Serialize state to JSON
- `load_tui_state()` - Load state from JSON (returns None if missing/stale)

**File watching:**
- `watch_tui_files(app)` - Async watcher that triggers reload on .py changes

**Reload:**
- `do_reload()` - Restart process via `os.execv`
- `app.trigger_reload()` - Save state, log, then restart

## Edge cases handled

- **Stale state**: Files older than 1 hour are ignored
- **Multiple instances**: PID in filename prevents collisions
- **Missing state**: Clean startup if no prior state exists
- **Syntax errors**: Process will crash (rely on pre-commit hooks)

## Development tips

Hot reload is most useful when:
- Iterating on TUI layout/styling
- Testing event handler changes
- Debugging widget interactions

Not recommended for:
- Agent logic changes (use stdout mode)
- Multi-turn conversation testing (state reset)
