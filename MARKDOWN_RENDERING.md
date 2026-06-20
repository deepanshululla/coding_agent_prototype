# Markdown Rendering in Terminal

## Overview

The agent now supports proper markdown rendering in the terminal TUI, including:

- **Syntax-highlighted code blocks** with automatic language detection
- **Inline code** with backticks
- **Bold** and *italic* text
- Headers, lists, and other markdown elements
- Streaming support for real-time responsiveness

## Implementation

The markdown rendering is implemented in `src/tui/components/transcript.py` using Rich's built-in markdown support:

### Features

1. **Code Block Detection**: The `TranscriptPane` widget detects code blocks (` ```lang ... ``` `) as they are streamed and renders them with syntax highlighting using Rich's `Syntax` class.

2. **Streaming Support**: Text is still streamed character-by-character for responsiveness, but complete code blocks are buffered and rendered properly once the closing ` ``` ` is detected.

3. **Syntax Highlighting**: Code blocks use the Monokai theme by default and support multiple languages (Python, JavaScript, etc.).

4. **Backward Compatible**: The implementation doesn't break existing functionality - plain text still streams normally.

## Usage

No changes needed - markdown rendering is automatic when using the TUI (`task tui`). The agent's responses that include code blocks or markdown syntax will be rendered properly.

## Demo

Run the demo script to see markdown rendering in action:

```bash
uv run python demo_markdown.py
```

This will show:
- Headers
- Bold and italic text
- Inline code
- Syntax-highlighted Python and JavaScript code blocks
- Lists (ordered and unordered)

## Testing

Tests are in `tests/test_markdown_rendering.py`:

```bash
uv run pytest tests/test_markdown_rendering.py -v
```

Tests cover:
- Basic markdown elements
- Code blocks with syntax highlighting
- Inline code
- Lists
- Streaming (character-by-character) rendering
- Multiple code blocks in one response
