Status: done

# Paste Images with Ctrl+V in the Terminal TUI

## Goal

Let a user paste an image from their OS clipboard into the agent conversation by
pressing **Ctrl+V** in the Textual TUI. The pasted image is attached to the next
steering message and sent to the model as a multimodal content block, so the user
can ask questions about screenshots, diagrams, error dialogs, etc.

## Key constraint (why this is not "just intercept Ctrl+V")

A terminal **does not send image bytes** when you press Ctrl+V — only text flows
through the PTY (bracketed paste covers text only). The clipboard's image data is
invisible to Textual. Therefore:

- `Ctrl+V` is only a **trigger**. On that keypress we shell out to an OS-specific
  command that reads the *current clipboard image* and returns its bytes.
- If the clipboard holds text (normal paste), we fall back to Textual's existing
  text paste behaviour — we do not hijack it.

### Platform clipboard-read strategy

| OS | Command | Notes |
|---|---|---|
| macOS | `osascript` writing `«class PNGf»` to a temp file | No third-party deps; `pngpaste` is not installed here. Use `the clipboard as «class PNGf»` → write to temp `.png`. Returns non-zero / empty when clipboard has no image. |
| Linux (Wayland) | `wl-paste --type image/png` | Used if `wl-paste` is on PATH. |
| Linux (X11) | `xclip -selection clipboard -t image/png -o` | Fallback if `xclip` is on PATH. |
| Windows / unsupported | return `None` | Feature degrades to a no-op with a status-bar hint. |

`read_clipboard_image()` returns `(png_bytes, mime)` or `None`. It never raises —
a missing tool or empty clipboard yields `None`.

## Message format sent to the model

LiteLLM accepts OpenAI-style multimodal content for Claude. A user message with
an image becomes:

```python
{
  "role": "user",
  "content": [
    {"type": "text", "text": "what does this error mean?"},
    {"type": "image_url",
     "image_url": {"url": "data:image/png;base64,<...>"}},
  ],
}
```

When no image is attached, `content` stays a plain string (unchanged behaviour).
This list shape already flows untouched through `agent.stream_turn` →
`provider.stream_response` → `litellm.acompletion`, so the core loop needs **no**
changes.

## Files changed

| File | Change |
|---|---|
| `src/tui/clipboard.py` | **New.** `read_clipboard_image() -> tuple[bytes, str] | None`; per-OS readers; `to_data_url(bytes, mime) -> str`. Pure, subprocess-based, never raises. |
| `src/tui/app.py` | Bind `ctrl+v` (priority). Add `_pending_images: list[dict]` buffer + `action_paste_image`. On submit, fold pending image blocks into the steering message content; clear the buffer. Show `[image N attached]` echo + status hint. |
| `src/tui/components/status_bar.py` | Add `set_hint(msg)` (or reuse existing transient slot) to report "image attached" / "no image in clipboard". |
| `src/provider.py` | `_messages_to_prompt` (the `claude -p` text-only fork) must handle **list** content: extract `text` parts, replace image blocks with `[image omitted — CLI fork is text-only]` so the fork never crashes on multimodal history. |
| `src/config.py` | `AGENT_IMAGE_PASTE` (default on) to gate the binding; `AGENT_IMAGE_MAX_BYTES` (default ~5 MB) to reject oversized clipboard images. |
| `tests/test_clipboard.py` | **New.** Monkeypatch subprocess: macOS path returns bytes; empty clipboard → `None`; unsupported platform → `None`; `to_data_url` formatting. |
| `tests/test_app_image_paste.py` | **New.** Pasting buffers an image block; submitting builds multimodal `content`; submitting with no image stays a plain string; oversized image rejected with hint. |
| `tests/test_provider.py` | Add: `_messages_to_prompt` flattens list/multimodal content without error. |

## Ordering (TDD per CLAUDE.md)

1. **Clipboard module** — write `tests/test_clipboard.py` first (mock subprocess
   for macOS success, empty-clipboard `None`, data-url format). Implement
   `src/tui/clipboard.py` to green.
2. **Provider safety** — failing `test_provider` case for list content →
   patch `_messages_to_prompt`.
3. **App wiring** — `tests/test_app_image_paste.py`: buffer-on-paste,
   multimodal-on-submit, plain-string fallback, size cap. Implement the binding,
   buffer, and submit-time content assembly in `app.py` + status hint.
4. **Manual verify** — run the TUI (`task tui` / `USE_CLAUDE_CLI` off so the
   LiteLLM multimodal path is exercised), copy a real screenshot, Ctrl+V, send a
   question, confirm the model describes the image. Record the observed result.

## Open questions / decisions

- **First-message images:** the initial `task` arg is a plain string from the CLI;
  interactive pastes always arrive via steering, so we only support images through
  the steering path. First-turn image paste works too because an empty initial
  task makes the agent wait for the first steering message (which can carry the
  image). No special-casing needed.
- **CLI fork (`USE_CLAUDE_CLI=1`) is text-only:** images are dropped with a clear
  placeholder rather than supported. Documented, not fixed, in this plan.
- **Multiple images:** buffer is a list, so N pastes before one Enter attach N
  images. Each Ctrl+V appends one block.