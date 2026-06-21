# Manual Test: Transcript Text Selection and Copying

## Setup
```bash
AGENT_UI=tui uv run main.py "list all python files"
```

## Test Steps

1. **Launch TUI and wait for agent response**
   - Run the command above
   - Wait for the agent to respond with text in the transcript pane

2. **Focus the transcript pane**
   - Click on the transcript pane with your mouse, OR
   - Use Tab to cycle focus until the transcript has a focus indicator

3. **Select text with mouse**
   - Click and drag in the transcript to select some text
   - Selected text should be highlighted

4. **Select text with keyboard**
   - Press Shift+Down arrow to extend selection downward
   - Press Shift+Up arrow to extend selection upward
   - Press Shift+End to select to end of line
   - Press Shift+Home to select to start of line

5. **Copy with Ctrl+C**
   - With text selected, press Ctrl+C
   - The text should be copied to clipboard
   - Paste into another application to verify (Cmd+V / Ctrl+V)

6. **Select all with Ctrl+A**
   - While transcript is focused, press Ctrl+A
   - All text in the transcript should be selected
   - Press Ctrl+C to copy
   - Verify by pasting elsewhere

7. **Verify Ctrl+C without selection still cancels**
   - Deselect all text (click elsewhere or Esc)
   - Press Ctrl+C
   - Should cancel the current agent turn (not copy)

## Expected Results

✅ Text can be selected with mouse and keyboard
✅ Ctrl+C copies selected text to clipboard
✅ Ctrl+A selects all transcript text
✅ Copied text pastes correctly in other apps
✅ Ctrl+C without selection still works for canceling
✅ Transcript maintains its formatting and colors
✅ Selection works alongside scrolling (j/k/g/G)

## Notes

- Selection uses system defaults (typically blue highlight)
- Works with both mouse and keyboard selection
- RichLog's formatting (colors, markdown) is preserved in display
- Copied text is plain text (formatting stripped, which is expected)
