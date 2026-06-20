---
sidebar_position: 5
title: Providers & Models
description: How the model string selects a provider, what LiteLLM normalizes, and a reference table of common model strings.
---

# Providers & Models

The entire provider abstraction is one string. Change `MODEL` in `src/provider.py` and the agent switches providers — nothing else in the codebase changes.

## How the model string selects a provider

LiteLLM infers the provider from the model string's prefix:

| Model string | Provider | Notes |
|---|---|---|
| `claude-sonnet-4-5` | Anthropic | No prefix needed; `claude-` is Anthropic's namespace |
| `claude-opus-4-5` | Anthropic | |
| `claude-haiku-3-5` | Anthropic | Fastest, cheapest Claude |
| `gemini/gemini-2.0-flash` | Google | `gemini/` prefix required |
| `gemini/gemini-1.5-pro` | Google | |
| `gpt-4o` | OpenAI | No prefix needed; `gpt-` is OpenAI's namespace |
| `gpt-4o-mini` | OpenAI | Cheaper, faster GPT-4o variant |
| `openrouter/anthropic/claude-sonnet-4-5` | OpenRouter | `openrouter/` prefix routes through OpenRouter |

:::note
`src/provider.py` is implemented. The `MODEL` constant is `"claude-sonnet-4-5"` by default. Changing that one line is all that's needed to switch providers.
:::

## Required environment variable per provider

Each provider reads its credentials from a standard env var that LiteLLM knows about. Set the one that matches your chosen model:

| Provider | Environment variable | Where to get it |
|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| Google | `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) |
| OpenAI | `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) |
| OpenRouter | `OPENROUTER_API_KEY` | [openrouter.ai](https://openrouter.ai) |

You do not need to instantiate a client or pass the key to any function. LiteLLM reads the env var automatically after `load_dotenv()` runs in `main.py`.

## What LiteLLM normalizes

Pi.dev's `packages/ai/` implements each provider's wire format by hand: Anthropic's `content` blocks, Google's `candidates`, OpenAI's `choices`. LiteLLM replaces all of that.

Regardless of which provider you use, `litellm.acompletion` yields OpenAI-format chunks:

```python
chunk.choices[0].delta.content          # text fragment, str | None
chunk.choices[0].delta.tool_calls       # list of tool-call fragments | None
chunk.choices[0].finish_reason          # "stop" | "tool_calls" | None
```

The agent loop in `src/agent.py` only ever sees this normalized format. The streaming accumulation logic — buffering tool-call argument fragments by `index`, then `json.loads()` after the stream ends — is the same regardless of provider.

Tool results are always sent back as `role: "tool"` messages:

```python
{"role": "tool", "tool_call_id": "...", "content": "..."}
```

LiteLLM translates these to whatever format the provider's API expects. From the loop's perspective, the format is fixed.

## Picking a model for development

For learning and local testing, prioritize speed and cost over quality:

- **`claude-haiku-3-5`** — fast, cheap, still good at tool use
- **`gemini/gemini-2.0-flash`** — very fast; free tier available on AI Studio
- **`gpt-4o-mini`** — fast, cheap OpenAI option

Switch to a more capable model (`claude-sonnet-4-5`, `gpt-4o`) when the task requires complex reasoning across many files.

:::tip
You can hard-code the model string during development and parameterize it later via an env var (`MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-4-5")`). This lets you switch models at the command line without touching code.
:::

## Related pages

- [Architecture: Provider Layer](../architecture/provider-layer.md) — how `stream_response()` is implemented and why async matters
- [Guides: Swapping Providers](../guides/swapping-providers.md) — step-by-step walkthrough for switching from Anthropic to another provider
- [Configuration](./configuration.md) — where to set the model string and env vars
