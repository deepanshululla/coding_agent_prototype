#!/usr/bin/env python3
"""Demo script to show markdown rendering in the transcript pane."""

from textual.app import App, ComposeResult

from tui.components.transcript import TranscriptPane


class MarkdownDemoApp(App):
    """Simple demo app showing markdown rendering."""

    CSS = """
    Screen {
        layout: vertical;
    }
    """

    def compose(self) -> ComposeResult:
        yield TranscriptPane(markup=False, highlight=False)

    async def on_mount(self) -> None:
        pane = self.query_one(TranscriptPane)

        # Demo: Stream some markdown content
        demo_content = """# Markdown Rendering Demo

This is a demonstration of **proper markdown rendering** in the terminal.

## Features

- **Bold** and *italic* text
- Inline code: `print("hello")`
- Headers at multiple levels

## Code Blocks

Here's a Python code block:

```python
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

result = factorial(5)
print(f"5! = {result}")
```

And here's some JavaScript:

```javascript
const greet = (name) => {
    console.log(`Hello, ${name}!`);
};

greet("World");
```

## Lists

1. First item
2. Second item
3. Third item

Nested lists work too:

- Top level
  - Nested item
  - Another nested item
- Back to top level

## Conclusion

The markdown renderer handles streaming text and renders code blocks with
proper syntax highlighting using Rich's Syntax class with the Monokai theme.
"""

        # Simulate streaming character by character
        for char in demo_content:
            pane.append_text(char)


if __name__ == "__main__":
    app = MarkdownDemoApp()
    app.run()
