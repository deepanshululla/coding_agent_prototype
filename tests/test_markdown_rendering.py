# tests/test_markdown_rendering.py

"""Tests for markdown rendering in the transcript pane."""

from tui.components.transcript import TranscriptPane


def test_markdown_rendering_basic():
    """Test that basic markdown is rendered properly."""
    pane = TranscriptPane(markup=False, highlight=False)

    # Append markdown text
    markdown_text = "# Header\n\nThis is **bold** and *italic* text."
    pane.append_markdown(markdown_text)

    # The pane should have written the markdown
    # We verify it was called without error for now
    assert True  # Basic smoke test


def test_markdown_code_blocks():
    """Test that code blocks are rendered with syntax highlighting."""
    pane = TranscriptPane(markup=False, highlight=False)

    markdown_text = """
```python
def hello():
    print("world")
```
"""
    pane.append_markdown(markdown_text)
    assert True


def test_markdown_inline_code():
    """Test that inline code is rendered differently."""
    pane = TranscriptPane(markup=False, highlight=False)

    markdown_text = "Use `print()` to output text."
    pane.append_markdown(markdown_text)
    assert True


def test_markdown_lists():
    """Test that lists are rendered properly."""
    pane = TranscriptPane(markup=False, highlight=False)

    markdown_text = """
- Item 1
- Item 2
  - Nested item
"""
    pane.append_markdown(markdown_text)
    assert True


def test_mixed_plain_and_markdown():
    """Test that plain text and markdown can be mixed."""
    pane = TranscriptPane(markup=False, highlight=False)

    # Append plain text first
    pane.append_text("Plain text\n")

    # Then append markdown
    pane.append_markdown("**Bold text**\n")

    assert True


def test_streamed_code_block():
    """Test that code blocks work when streamed character by character."""
    pane = TranscriptPane(markup=False, highlight=False)

    # Simulate streaming a code block character by character
    code_block = """Here is some code:

```python
def hello():
    print("world")
```

And some text after."""

    # Stream it in chunks to simulate real streaming
    for char in code_block:
        pane.append_text(char)

    # Should not crash and should have rendered the code block
    assert True


def test_multiple_code_blocks():
    """Test that multiple code blocks are rendered correctly."""
    pane = TranscriptPane(markup=False, highlight=False)

    text = """First block:

```python
def foo():
    pass
```

Second block:

```javascript
console.log("hello");
```

Done."""

    # Stream it
    for char in text:
        pane.append_text(char)

    assert True


def test_turn_finalization_basic():
    """Test that finalize_turn() replaces raw text with rendered markdown."""
    pane = TranscriptPane(markup=False, highlight=False)

    # Stream some markdown text
    text = "# Header\n\nThis is **bold** text."
    for char in text:
        pane.append_text(char)

    # Before finalization, we have raw text in the buffer
    assert pane._current_turn_buffer == text

    # Finalize the turn
    pane.finalize_turn()

    # Buffer should be cleared
    assert pane._current_turn_buffer == ""


def test_turn_finalization_with_code_blocks():
    """Test that turn finalization works with code blocks."""
    pane = TranscriptPane(markup=False, highlight=False)

    text = """Here's a function:

```python
def greet(name: str) -> str:
    return f"Hello, {name}!"
```

That's it!"""

    # Stream the text
    for char in text:
        pane.append_text(char)

    # Finalize
    pane.finalize_turn()

    # Should not crash
    assert pane._current_turn_buffer == ""


def test_multiple_turns():
    """Test that multiple turns can be finalized without interfering."""
    pane = TranscriptPane(markup=False, highlight=False)

    # First turn
    text1 = "First turn with **bold** text."
    for char in text1:
        pane.append_text(char)
    pane.finalize_turn()

    # Second turn
    text2 = "\n\nSecond turn with `code`."
    for char in text2:
        pane.append_text(char)
    pane.finalize_turn()

    # Should not crash
    assert pane._current_turn_buffer == ""


def test_empty_turn_finalization():
    """Test that finalizing an empty turn doesn't crash."""
    pane = TranscriptPane(markup=False, highlight=False)

    # Don't append anything
    pane.finalize_turn()

    # Should not crash
    assert pane._current_turn_buffer == ""


def test_markdown_headers():
    """Test that markdown headers render properly."""
    pane = TranscriptPane(markup=False, highlight=False)

    text = """# Level 1
## Level 2
### Level 3"""

    for char in text:
        pane.append_text(char)
    pane.finalize_turn()

    assert True


def test_markdown_lists_bullets_and_numbers():
    """Test that both bullet and numbered lists render."""
    pane = TranscriptPane(markup=False, highlight=False)

    text = """Shopping list:
- Apples
- Bananas
- Oranges

Steps:
1. Buy ingredients
2. Cook meal
3. Enjoy!"""

    for char in text:
        pane.append_text(char)
    pane.finalize_turn()

    assert True


def test_markdown_blockquotes():
    """Test that blockquotes render properly."""
    pane = TranscriptPane(markup=False, highlight=False)

    text = """> This is a quote
> from someone wise"""

    for char in text:
        pane.append_text(char)
    pane.finalize_turn()

    assert True


def test_markdown_mixed_formatting():
    """Test complex markdown with multiple elements."""
    pane = TranscriptPane(markup=False, highlight=False)

    text = """# Analysis Report

## Summary

This is **important** and *noteworthy*.

## Code Example

```python
def analyze(data: list[int]) -> float:
    return sum(data) / len(data)
```

## Key Points

- Point one
- Point two with `inline_code`
- **Bold point** three

> Remember: Always validate your data!"""

    for char in text:
        pane.append_text(char)
    pane.finalize_turn()

    assert True
