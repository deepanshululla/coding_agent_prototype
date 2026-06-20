---
sidebar_position: 4
title: Custom Models
description: How to change the MODEL constant, select models per-task, tune max_tokens and temperature, and choose between reasoning and fast models.
---

# Custom Models

Swapping models is the most common customization you'll make. LiteLLM normalizes all providers to OpenAI's format, so changing the model is a one-line edit in `src/provider.py`. This page covers how to do that, how to select models per-task, and how to tune generation parameters.

## The `MODEL` constant

`src/provider.py` defines a single module-level constant:

```python
MODEL = "claude-sonnet-4-5"
```

This string is passed to `litellm.acompletion` on every call. Change it to switch providers or model versions:

```python
MODEL = "gpt-4o"                       # OpenAI
MODEL = "gemini/gemini-2.0-flash"      # Google via LiteLLM prefix
MODEL = "claude-opus-4-5"              # Anthropic, more capable, slower
MODEL = "ollama/llama3.2"              # Local Ollama instance
```

The prefix before the first `/` (when present) tells LiteLLM which provider adapter to use. No prefix means Anthropic. See [Custom Providers](./custom-providers.md) for how prefixes work.

:::note
The `MODEL` constant and `stream_response` function shown above reflect the shipped `src/provider.py`. The per-task model selection and `temperature` patterns in the sections below show how to extend `stream_response` — they are not in the v1 implementation.
:::

## Model reference table

| Model string | Provider | Relative speed | Relative cost | Good for |
|---|---|---|---|---|
| `claude-sonnet-4-5` | Anthropic | Fast | Mid | Default — balanced |
| `claude-opus-4-5` | Anthropic | Slow | High | Hard reasoning, multi-file refactors |
| `claude-haiku-3-5` | Anthropic | Very fast | Low | Quick lookups, summarization |
| `gpt-4o` | OpenAI | Fast | Mid | General purpose |
| `gpt-4o-mini` | OpenAI | Very fast | Low | Cheap tasks, drafting |
| `gemini/gemini-2.0-flash` | Google | Fast | Low | Cost-efficient alternative |
| `gemini/gemini-2.5-pro` | Google | Slow | High | Long-context tasks |
| `ollama/llama3.2` | Local | Varies | Free | Offline, private codebases |
| `openai/your-model` | Any OpenAI-compatible API | — | — | Self-hosted or proxy endpoints |

:::tip
Always verify the exact model string against LiteLLM's provider documentation — model names change with provider releases. Run `litellm --list_models` or check [docs.litellm.ai](https://docs.litellm.ai/docs/providers) for the current list.
:::

## Per-task model selection

Sometimes you want a cheap model for exploration and a powerful model for final edits. Pass the model as an argument to `stream_response`:

```python
# src/provider.py

MODEL = "claude-sonnet-4-5"   # default

async def stream_response(
    messages: list[dict],
    system_prompt: str,
    model: str | None = None,
    max_tokens: int = 8096,
    temperature: float | None = None,
):
    effective_model = model or MODEL
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    kwargs = dict(
        model=effective_model,
        messages=full_messages,
        tools=TOOLS_SCHEMA,
        tool_choice="auto",
        max_tokens=max_tokens,
        stream=True,
    )
    if temperature is not None:
        kwargs["temperature"] = temperature

    response = await litellm.acompletion(**kwargs)
    async for chunk in response:
        yield chunk
```

Then from `src/agent.py`:

```python
# Use a fast model for the first pass
async for chunk in stream_response(messages, system_prompt, model="claude-haiku-3-5"):
    ...

# Use a reasoning model for the final synthesis
async for chunk in stream_response(messages, system_prompt, model="claude-opus-4-5"):
    ...
```

## `max_tokens` and `temperature`

Both are passed directly to `litellm.acompletion`.

### `max_tokens`

Controls the maximum number of tokens the model can generate in a single response. The plan uses `8096` as the default. Raise it if the model is truncating long file writes or cut off mid-tool-call. Lower it if you're using a cheap model for quick responses and want to cap cost.

```python
# Long-form tasks (large file writes, detailed explanations)
async for chunk in stream_response(messages, system_prompt, max_tokens=16384):
    ...

# Quick, bounded responses
async for chunk in stream_response(messages, system_prompt, max_tokens=1024):
    ...
```

### `temperature`

Controls randomness. Default is provider-dependent (usually 1.0). For a coding agent:

| Use case | Recommended temperature |
|---|---|
| Code editing, precise tool calls | `0.0` — deterministic |
| Code generation, brainstorming | `0.2`–`0.5` |
| Creative tasks, documentation drafts | `0.7`–`1.0` |

```python
# Deterministic edits
async for chunk in stream_response(messages, system_prompt, temperature=0.0):
    ...
```

:::warning
Not all providers honor `temperature=0.0` exactly. Some add a small floor. Don't rely on exact reproducibility across providers.
:::

## Reasoning vs. fast models — when to use each

Coding agents typically face two types of sub-tasks:

**Reasoning tasks** — multi-file understanding, planning a refactor, debugging a non-obvious failure. These benefit from more capable, slower models (`claude-opus-4-5`, `gemini/gemini-2.5-pro`).

**Fast tasks** — reading a file to answer a quick question, running a lint check, listing a directory. A cheaper, faster model handles these fine.

A simple heuristic for per-task selection:

```python
def pick_model(task: str) -> str:
    reasoning_keywords = ["refactor", "design", "architecture", "debug", "why", "explain"]
    if any(kw in task.lower() for kw in reasoning_keywords):
        return "claude-opus-4-5"
    return "claude-sonnet-4-5"   # default for execution tasks
```

This is a rough heuristic. A more principled approach is to always start with a fast model and escalate only when the model signals low confidence — but that requires inspecting the model's output, which adds complexity better deferred to a later iteration.

## Extended thinking

Anthropic's `claude-opus-4-5` and `claude-sonnet-4-5` support an extended thinking mode that lets the model reason step-by-step before generating its response. PLAN.md lists this as "nice to have, not essential" for v1.

If you want to enable it:

```python
response = await litellm.acompletion(
    model="claude-opus-4-5",
    messages=full_messages,
    tools=TOOLS_SCHEMA,
    max_tokens=16000,
    thinking={"type": "enabled", "budget_tokens": 5000},  # Anthropic-specific
    stream=True,
)
```

:::warning
LiteLLM passes unknown parameters through to the provider. The `thinking` parameter works with Anthropic but will error or be ignored on other providers. Guard it with a provider check if your code needs to run across providers.
:::

## Changing the model at the CLI

A minimal flag on `main.py`:

```python
import argparse

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("task", nargs="+")
    parser.add_argument("--model", default=None, help="LiteLLM model string")
    args = parser.parse_args()

    task = " ".join(args.task)
    await run_agent(task, model=args.model)
```

```bash
uv run main.py --model gpt-4o "add type hints to tools.py"
uv run main.py --model ollama/llama3.2 "list all .py files"
```

## Related pages

- [Custom Providers](./custom-providers.md) — configuring LiteLLM for different backends
- [Providers and Models](../getting-started/providers-and-models.md) — full provider reference
- [Swapping Providers](../guides/swapping-providers.md) — step-by-step guide to switching backends
