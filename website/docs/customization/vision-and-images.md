---
sidebar_position: 4.5
title: Vision & Images
description: How read_file delivers images to the model — whole-image delivery for vision models, optional in-tool VLM captioning, and the AGENT_IMAGE_MODE / AGENT_VLM_MODEL settings.
---

# Vision & Images

When the `read_file` tool reads an image (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp`, `.ico`, `.svg`), it can deliver that image to the model in three ways, chosen by one setting. By default the model sees the **whole image**; if you point at a vision model it can also attach a text **caption**. This page covers both knobs and when to use each.

The mechanism and rationale are recorded in [ADR-0016](../architecture-decisions.md#adr-0016--images-reach-the-model-whole-vlm-captioning-is-an-in-tool-option).

## Why this needs a setting

A tool result is **plain text** to every provider — the OpenAI / LiteLLM contract carries images only as *user-message* content blocks, never inside a `role:"tool"` message. So an image read can't just be "returned" as a viewable image. Two paths solve it, and they suit different models:

- A **vision-capable** model (Claude, `qwen3-vl`, `gemma4`, GPT-4o…) should see the **real pixels**.
- A **non-vision** driver (e.g. `ollama/qwen3-coder`, `gpt-oss`) can't accept pixels at all, so it needs a **text description** instead.

## The two settings

| Env var | Default | What it does |
|---|---|---|
| `AGENT_IMAGE_MODE` | `both` | How `read_file` delivers an image: `raw`, `caption`, or `both`. |
| `AGENT_VLM_MODEL` | _(empty)_ | A vision model used **inside** `read_file` to caption images. Required for `caption`/`both`. |

### `AGENT_IMAGE_MODE`

| Mode | `read_file` returns | The model receives | Use when |
|---|---|---|---|
| **`both`** (default) | image payload **+** caption (if a VLM is set) | the whole image **and** a caption | your `MODEL` is vision-capable and you also want a VLM's read |
| `raw` | image payload | the whole image | your `MODEL` is vision-capable; no VLM call wanted |
| `caption` | caption text only | text only | your driver `MODEL` is **non-vision** |

`caption` and `both` need `AGENT_VLM_MODEL`. **Without it they degrade to `raw`** — there's no VLM to caption with, so you still get the whole image.

### `AGENT_VLM_MODEL`

A vision model reached **inside the `read_file` tool** (read live, exactly like `CODE_MODEL` is reached inside `write_code` — see [ADR-0015](../architecture-decisions.md#adr-0015--one-model-per-loop-defer-dual-model-role-routing)). It is called with **no tools attached**, so it only describes the image — it never makes a tool call.

## How it flows

```
driver MODEL  ──calls──▶  read_file("chart.png")
                              │
        AGENT_IMAGE_MODE ─────┤
        raw/both              │  (both/caption) → describe_image(AGENT_VLM_MODEL, NO tools) → caption text
                              ▼
        returns an image payload (+caption in `both`)
                              │
   provider lifts it ─────────┤  base64 tool-result → viewable image_url block on a user message
                              ▼
   driver MODEL SEES the whole image (and reads the caption as the tool-result text)
```

The lift (`_lift_tool_image_results` in `src/provider.py`) is non-mutating and provider-agnostic, and batches a tool batch's images into one trailing user message so the `tool_result` grouping providers require is preserved.

## Recipes

**Vision model, see everything (default — nothing to set):**
```bash
AGENT_MODEL=ollama/qwen3-vl:30b      # or claude-sonnet-4-5, gemma4, gpt-4o
# AGENT_IMAGE_MODE defaults to "both"; with no VLM it sends the whole image.
```

**Non-vision driver + a vision model for descriptions:**
```bash
AGENT_MODEL=ollama/qwen3-coder:30b   # drives the loop, makes tool calls (cannot see pixels)
AGENT_VLM_MODEL=ollama/qwen3-vl:30b  # captions images inside read_file
AGENT_IMAGE_MODE=caption             # text only — never send pixels to a non-vision model
```

**Vision driver that also wants a VLM's structured read (e.g. OCR):**
```bash
AGENT_MODEL=ollama/qwen3-vl:30b
AGENT_VLM_MODEL=ollama/qwen3-vl:30b
AGENT_IMAGE_MODE=both                # the default — whole image + caption
```

## Caveats

- **Don't send pixels to a non-vision model.** With `raw` or `both`, the whole image is delivered to `MODEL`; a model with no vision support can **error** at the provider (not just ignore it). For a text-only driver use `AGENT_IMAGE_MODE=caption` with a VLM.
- **Captioning costs a round-trip.** Each captioned image read makes a blocking VLM call and is lossy versus the real pixels — prefer `raw`/`both` when `MODEL` can see.
- **Local Ollama needs Pillow.** LiteLLM's Ollama image path requires it; it's a project dependency (`pillow`), so a fresh `uv sync` covers it.

## See also

- [Built-in Tools](../tools/built-in-tools.md) — `read_file` and the rest of the toolbox.
- [Custom Models](./custom-models.md) and [Providers & Models](../getting-started/providers-and-models.md) — selecting `MODEL`.
- [ADR-0016](../architecture-decisions.md#adr-0016--images-reach-the-model-whole-vlm-captioning-is-an-in-tool-option) — the decision behind this design.
