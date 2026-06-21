---
"coding-agent-from-scratch": minor
---

Add image reading support to the read_file tool

The agent can now read image files (PNG, JPG, JPEG, GIF, WebP, BMP, ICO, SVG) through the read_file tool. Images are automatically detected by extension and returned as base64-encoded JSON in the format:

```json
{"type": "image", "format": "png", "data": "base64..."}
```

This complements the existing Ctrl+V clipboard paste feature in TUI mode - now both pasting images and reading image files from disk work seamlessly with multimodal models like Claude, GPT-4V, and Gemini Vision.

Changes:
- Extended read_file tool to detect image extensions and return base64 JSON
- Added comprehensive tests for image reading (7 new tests)
- Updated tool schema documentation
- Added demo script (demo_image_read.py)
- Updated README with image support documentation
