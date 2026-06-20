---
sidebar_position: 1
title: Swapping Providers
description: How to change the model string in provider.py to switch between Anthropic, Google, and OpenAI — one line, nothing else changes.
---

# Swapping Providers

The entire provider abstraction lives in one line of `src/provider.py`:

```python
MODEL = "claude-sonnet-4-5"
```

Change that string, set the matching API key, and the agent works with a different provider. The loop, the tools, the streaming accumulation — none of it changes. LiteLLM normalizes every provider's wire format to OpenAI's chunk structure before the agent sees it.

:::note
`src/provider.py` is implemented. The walkthrough below applies directly to the shipped file.
:::

## Step-by-step: switching to Gemini

### 1. Open `src/provider.py` and change the model string

```python
# Before
MODEL = "claude-sonnet-4-5"

# After
MODEL = "gemini/gemini-2.0-flash"
```

The `gemini/` prefix is required — that's how LiteLLM identifies the Google provider. Without it, LiteLLM will not route to Google.

### 2. Set the API key for the new provider

Add the key to your `.env` file (or export it in your shell):

```bash
# .env
GEMINI_API_KEY=your-key-here
```

Get a key at [aistudio.google.com](https://aistudio.google.com) — there is a free tier.

Remove or comment out `ANTHROPIC_API_KEY` if you want to be sure the old credential is not picked up.

### 3. Run the agent

```bash
uv run main.py "list all .py files in src/"
```

Output looks identical. The model badge in the streamed text is not shown (this is stdout-only), so the only visible difference is response latency and, occasionally, tool-call phrasing.

---

## Switching to GPT-4o

```python
MODEL = "gpt-4o"
```

```bash
# .env
OPENAI_API_KEY=sk-...
```

No prefix needed — `gpt-` is OpenAI's namespace and LiteLLM recognizes it directly.

---

## What stays identical when you swap

LiteLLM normalizes all providers to OpenAI's streaming chunk format. The agent loop never sees provider-specific wire formats.

| Thing you'd expect to change | What actually happens |
|---|---|
| Streaming chunk shape | Unchanged — always `chunk.choices[0].delta.*` |
| Tool call fragment format | Unchanged — always buffered by `.index`, parsed after stream ends |
| `finish_reason` values | Unchanged — always `"stop"` or `"tool_calls"` |
| Tool result message format | Unchanged — always `{"role": "tool", "tool_call_id": ..., "content": ...}` |
| `TOOL_REGISTRY` dispatch | Unchanged — tool functions are pure Python, provider-agnostic |
| System prompt | Unchanged — sent as `{"role": "system", "content": ...}` in every case |

The only thing that changes is the network destination and which API key is read from the environment.

---

## Gotchas table

| Gotcha | Detail |
|---|---|
| Missing prefix on Gemini | `"gemini-2.0-flash"` without the `gemini/` prefix is not recognized; LiteLLM will raise a `BadRequestError`. Always use `"gemini/gemini-2.0-flash"`. |
| Wrong env var for the provider | LiteLLM reads a specific env var per provider (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`). Putting the key in the wrong var silently fails with an auth error. |
| Max tokens differ per model | `MAX_TOKENS = 8096` is set in `src/provider.py`. Some models have lower limits — check the provider's docs if you get a `max_tokens exceeds` error and lower the value in `provider.py`. |
| Tool-call support varies | All major models (Claude, GPT-4o, Gemini 2.0 Flash) support tool use. Older or smaller models may not — the agent will stall because `finish_reason` never becomes `"tool_calls"`. |
| Rate limits during development | Free-tier keys (e.g. Gemini AI Studio) have low RPM limits. If you hit them during testing, add a short sleep between iterations or switch to a paid key. |
| Async requirement | The agent uses `litellm.acompletion` (async). Do not swap in the sync `litellm.completion` — it blocks the event loop during streaming and prevents parallel tool execution. |

---

## Parameterizing the model via env var

Hard-coding is fine while learning. When you want to switch providers at the command line without touching code, change `provider.py` to:

```python
import os

MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-4-5")
```

Then:

```bash
AGENT_MODEL=gemini/gemini-2.0-flash uv run main.py "refactor tools.py"
```

---

## Related pages

- [Providers & Models](../getting-started/providers-and-models.md) — full reference table of model strings, providers, and env vars
- [Configuration](../getting-started/configuration.md) — where to set env vars and the model string
