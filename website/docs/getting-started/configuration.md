---
sidebar_position: 3
title: Configuration
description: Configure the agent's .env file, choose a provider, set the model string, and tune iteration and token limits.
---

# Configuration

The agent reads all configuration from environment variables and two constants in `src/provider.py`. There is no config file beyond `.env`.

## The `.env` file

Create `.env` at the repo root (the same directory as `main.py`):

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...
```

`main.py` calls `load_dotenv()` as its first action, which loads this file into `os.environ` before anything else runs:

```python
from dotenv import load_dotenv

async def main():
    load_dotenv()   # must come before any litellm call
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Task: ")
    await run_agent(task)
```

LiteLLM then reads the standard env var names automatically — you never pass credentials explicitly to any function.

:::warning
Add `.env` to your `.gitignore`. Never commit API keys.
:::

## Provider environment variables

Pick the provider you want and set the corresponding key:

| Provider | Environment variable | Example value |
|---|---|---|
| Anthropic (Claude) | `ANTHROPIC_API_KEY` | `sk-ant-api03-...` |
| Google (Gemini) | `GEMINI_API_KEY` | `AIza...` |
| OpenAI | `OPENAI_API_KEY` | `sk-proj-...` |

You only need to set the key for the provider you're actually using. LiteLLM infers which key to look up from the model string.

## The `MODEL` constant

Open `src/provider.py` and change one line to switch providers:

```python
MODEL = "claude-sonnet-4-5"         # Anthropic — default
# MODEL = "gemini/gemini-2.0-flash" # Google
# MODEL = "gpt-4o"                  # OpenAI
```

The model string is the only thing that determines which provider and which model are used. LiteLLM normalizes the response format across all providers, so the rest of the code is unchanged. See [Providers & Models](./providers-and-models.md) for a full table.

:::note
`src/provider.py` is implemented. The `MODEL` constant defaults to `"claude-sonnet-4-5"` and `MAX_TOKENS` is `8096`.
:::

## Token and iteration limits

Two constants control how much the agent can do per run:

**`max_tokens`** in `src/provider.py` — the maximum number of tokens the model generates per turn (each inner-loop iteration):

```python
response = await litellm.acompletion(
    model=MODEL,
    messages=full_messages,
    tools=TOOLS_SCHEMA,
    tool_choice="auto",
    max_tokens=8096,   # adjust here
    stream=True,
)
```

**`MAX_ITERATIONS`** in `src/agent.py` — the hard cap on inner-loop iterations per run. Prevents runaway agents:

```python
MAX_ITERATIONS = 30
```

For quick exploratory tasks, 30 iterations is generous. For large refactors across many files, you might raise it. Each iteration is one round-trip to the model, which may involve multiple parallel tool calls.

:::tip
If the agent stops unexpectedly on a complex task, check whether it hit `MAX_ITERATIONS`. The loop exits silently when the cap is reached.
:::

## Full settings reference

For a complete list of all configurable fields, see [operations/settings](../operations/settings.md).

## Next steps

- [Providers & Models](./providers-and-models.md) — how the model string maps to a provider
- [Quickstart](./quickstart.md) — run the agent now that it's configured
