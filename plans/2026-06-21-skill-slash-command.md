# Add `/skill` slash command to TUI

**Status:** done  
**Date:** 2026-06-21

## Goal

Let users list and load skills via `/skill` and `/skill <name>` commands in the TUI.

## Why

Skills are currently invisible in the TUI — users don't know what's installed or how to access skill instructions. Adding a slash command makes them discoverable and accessible.

## File-by-file changes

| File | Change | Test coverage |
|------|--------|---------------|
| `src/tui/commands.py` | Add `_cmd_skill(arg: str \| None)` handler using `@command` decorator. If `arg` is None, list all skills from `.claude/skills/`. If `arg` is a skill name, load and return its SKILL.md contents. Return error if skill not found. | New test file |
| `tests/test_tui_skill_command.py` | 4 tests: (1) `/skill` lists all skills, (2) `/skill changelog` loads the skill, (3) `/skill unknown` returns error, (4) `/skill` when no skills installed returns empty list message. | N/A (this is the test) |
| `README.md` | Document `/skill` and `/skill <name>` in the TUI slash commands section. | Manual verification |

## Implementation order

1. **Write failing tests** in `test_tui_skill_command.py` (TDD loop)
2. **Implement `_cmd_skill()`** in `commands.py` to make tests pass
3. **Verify manually** in the TUI with real skill
4. **Document** in README.md

## Design decisions

**Should `/skill <name>` inject the skill into the conversation context, or just display it?**

→ **Decision: Just display** (keeps command simple; agent can still call `load_skill` tool to inject into context)

## Results

- ✅ All 4 new tests pass
- ✅ All 16 existing TUI tests still pass
- ✅ Manual verification confirms command works
- ✅ `/help` now lists `/skill` command
- ✅ README.md updated with documentation

## Files changed

- `src/tui/commands.py` — Added `_cmd_skill()` handler
- `tests/test_tui_skill_command.py` — Added comprehensive test coverage
- `README.md` — Documented new slash command
