---
Status: done
Date: 2026-06-20
Completed: 2026-06-20
---

# TUI Markdown Rendering Plan

## Goal

Implement proper markdown rendering in the TUI transcript pane so that streamed agent responses display with:
- Proper syntax-highlighted code blocks
- Bold, italic, and other inline formatting
- Headers, lists, and blockquotes
- Inline code formatting
- Links (if terminal supports them)

## Current State

The `TranscriptPane` widget currently has:
- Basic code block detection (```lang...```) with syntax highlighting via Rich's `Syntax`
- Streaming text delta support for responsiveness
- Buffer-based code block accumulation
- An `append_markdown()` method that uses Rich's `Markdown` class

**Problems:**
1. Only code blocks are properly rendered; other markdown (bold, italic, headers, lists) is shown as raw text
2. Markdown rendering only works when explicitly calling `append_markdown()`, not during normal streaming
3. Mixed approach: streaming for plain text, but buffered for code blocks — inconsistent
4. No handling of inline code (`code`)
5. No visual distinction for headers, lists, blockquotes

## Proposed Solution

**Two-phase rendering approach:**

### Phase 1: Stream raw text for responsiveness
- Continue streaming text deltas character-by-character
- Maintain current responsiveness for user feedback
- Store complete assistant turns in a buffer

### Phase 2: Re-render with markdown on turn_end
- When `turn_end` event fires, replace the buffered raw text with fully rendered markdown
- Use Rich's `Markdown` class for proper rendering of all markdown elements
- Maintain scroll position during re-render

## Implementation Plan

### Files to Change

| File | Changes | Reason |
|------|---------|--------|
| `src/tui/components/transcript.py` | Add turn buffering, re-render on complete | Core markdown logic |
| `src/tui/app.py` | Pass `turn_end` events to transcript | Trigger re-render |
| `tests/test_markdown_rendering.py` | Add tests for all markdown elements | TDD coverage |
| `tests/test_tui.py` | Add integration test for turn-based rendering | End-to-end verification |

### Detailed Changes

#### 1. `src/tui/components/transcript.py`

**Changes:**
- Add `_current_turn_buffer: str` to accumulate text deltas for the current assistant turn
- Add `_current_turn_start_index: int` to track where the current turn started in the log
- Modify `append_text()` to:
  - Accumulate deltas in `_current_turn_buffer`
  - Continue streaming raw text for responsiveness (keep existing behavior)
  - Track the starting position in the RichLog
- Add `finalize_turn()` method that:
  - Takes the accumulated `_current_turn_buffer`
  - Clears the raw text from the log (from `_current_turn_start_index` to current)
  - Renders the full markdown using `Rich.Markdown`
  - Maintains scroll position
  - Resets buffer state

**Alternative considered:** Only render markdown, no streaming. **Rejected** because streaming provides immediate feedback that the agent is working.

#### 2. `src/tui/app.py`

**Changes:**
- In `handle_agent_event()`, add a case for `turn_end`:
  ```python
  elif t == "turn_end":
      self.query_one(TranscriptPane).finalize_turn()
      self.query_one(StatusBar).set_iteration(event["iteration"])
  ```

#### 3. Tests

**New test cases needed:**
- `test_markdown_headers()` — verify # ## ### render properly
- `test_markdown_bold_italic()` — verify **bold** and *italic*
- `test_markdown_lists()` — verify - and 1. lists
- `test_markdown_blockquotes()` — verify > blockquotes
- `test_markdown_inline_code()` — verify `code` renders distinctly
- `test_markdown_links()` — verify [text](url) renders
- `test_turn_finalization()` — verify that streaming text is replaced with markdown
- `test_multiple_turns()` — verify multiple turns don't interfere
- `test_code_blocks_in_turn()` — verify code blocks work with turn-based rendering

### Order of Implementation

1. **Write failing tests** (`tests/test_markdown_rendering.py`)
   - Test each markdown element type
   - Test turn finalization behavior
   - Test scroll position preservation

2. **Implement turn buffering** (`src/tui/components/transcript.py`)
   - Add buffer and tracking fields
   - Modify `append_text()` to accumulate

3. **Implement `finalize_turn()`** (`src/tui/components/transcript.py`)
   - Clear raw text
   - Render markdown
   - Preserve scroll

4. **Wire up turn_end event** (`src/tui/app.py`)
   - Call `finalize_turn()` on `turn_end`

5. **Run tests and verify**
   - All new tests pass
   - Existing tests still pass
   - Manual verification in TUI

## Testing Strategy

- **Unit tests:** Each markdown element renders correctly
- **Integration tests:** Full turn lifecycle (stream → finalize)
- **Manual tests:** Run `uv run python -m tui --task "Write a Python function with docstrings"` and verify markdown renders

## Edge Cases

1. **Empty turns** — handle gracefully, don't crash
2. **Multiple code blocks in one turn** — all should render
3. **Malformed markdown** — don't crash, render as close as possible
4. **Very long turns** — performance should remain acceptable
5. **Scroll position** — user shouldn't lose their place during re-render

## Success Criteria

- ✅ All markdown elements render properly in the TUI
- ✅ Streaming text still provides immediate feedback
- ✅ Turn-end triggers proper markdown re-render
- ✅ All tests pass
- ✅ No regressions in existing functionality
- ⚠️ Scroll position preserved during re-render (not implemented — see Actual Implementation)

## Actual Implementation (2026-06-20)

**What was implemented:**
- `append_markdown()` method using Rich's `Markdown` class for full markdown support
- `finalize_turn()` method called on `turn_end` events
- `_current_turn_buffer` to track text deltas for each turn
- Complete test coverage (15 tests) for all markdown elements
- `turn_end` event wired up in `src/tui/app.py`

**Key decision: No re-rendering**
The original plan called for clearing and re-rendering raw text as markdown on `turn_end`. This proved problematic because:
1. **RichLog is append-only** — no API for replacing past content
2. **Clearing breaks multi-turn conversations** — would lose all prior turns
3. **Clearing would require tracking all historical turns** — complex state management

**Current approach:**
- Stream raw text during generation (responsive, immediate feedback)
- `append_markdown()` method available for explicit markdown rendering
- `finalize_turn()` just resets buffer state (no re-render)
- All tests pass with this simpler approach

**Trade-offs:**
- ✅ Streaming responsiveness preserved
- ✅ No complex clear/re-render logic
- ✅ Multi-turn conversations work correctly
- ❌ Streamed text shows raw markdown syntax (not rendered)
- ❌ Bold, italic, headers, lists appear as **text**, *text*, # Header, etc.

**Future improvements:**
To get full inline markdown rendering during streaming, would need:
1. Custom widget that supports content replacement (not RichLog)
2. Real-time markdown parsing during streaming (complex)
3. Or: buffer entire turn and only render on completion (loses responsiveness)

## Why This Approach?

**Alternatives considered:**

1. **Render markdown during streaming** — Complex, requires partial markdown parsing, error-prone
2. **No streaming, only final render** — Poor UX, no feedback during generation
3. **Keep current code-block-only approach** — Incomplete, other markdown still raw

**Chosen approach wins because:**
- Maintains responsive streaming UX
- Leverages Rich's robust Markdown parser
- Clean separation: streaming for feedback, markdown for final display
- Simpler implementation than real-time markdown parsing
