# TUI Slash Command Autocomplete

**Status:** done  
**Date:** 2026-06-21

## Goal

Add autocomplete for slash commands in the TUI input box. When the user types `/`, show available commands and allow Tab-completion to cycle through matches.

## Approach

Simple inline autocomplete using Tab key:
- When input starts with `/`, Tab cycles through matching commands
- Shift+Tab cycles backward
- Show hint in status bar with available completions

## File Changes

| File | Change | Test |
|------|--------|------|
| `src/tui/commands.py` | Add `get_command_names()` to export registered commands | Unit test |
| `src/tui/components/input_box.py` | Override `on_key` to handle Tab for autocomplete, track completion state | Unit test |
| `src/tui/app.py` | Wire status bar hints for autocomplete feedback | Manual test |
| `tests/test_tui_autocomplete.py` | Test Tab-completion behavior | Pytest |

## Implementation Steps

1. **Export command names** (`commands.py`):
   - Add `get_command_names() -> list[str]` function
   - Returns sorted list of registered command names

2. **Add autocomplete to InputBox** (`input_box.py`):
   - Track completion state: `_completion_candidates`, `_completion_index`
   - Override `on_key` to intercept Tab/Shift+Tab
   - Filter commands matching current input prefix
   - Replace input value with selected completion

3. **Test coverage**:
   - `/` + Tab shows all commands
   - `/mo` + Tab completes to `/model`
   - Multiple Tab presses cycle through matches
   - Non-slash text doesn't trigger autocomplete
   - Editing resets completion state

## Testing

```bash
uv run pytest tests/test_tui_autocomplete.py -v
```

Manual test: Run TUI, type `/`, press Tab, verify completion cycling.
