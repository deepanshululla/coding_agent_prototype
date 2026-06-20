---
sidebar_position: 5
title: The Provider Layer
description: How provider.py wraps litellm.acompletion into a single async stream_response() function, why async matters, and how LiteLLM replaces 40+ hand-rolled provider adapters.
---

# The Provider Layer

`src/provider.py` is the thinnest module in the project: one function, one call to LiteLLM, an async generator. Its simplicity is the point. All the complexity of provider differences — authentication, request formats, chunk shapes, retry behavior — is delegated to LiteLLM.

:::note
`src/provider.py` is implemented. The code below matches the shipped file.
:::

## The complete `provider.py`

```python
import litellm
from tools import TOOLS_SCHEMA

MODEL = "claude-sonnet-4-5"   # swap to "gemini/gemini-2.0-flash" or "gpt-4o" freely

async def stream_response(messages: list[dict], system_prompt: str):
    """
    Streams from any LiteLLM-supported provider.
    Yields OpenAI-compatible chunks regardless of the underlying model.
    """
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    response = await litellm.acompletion(
        model=MODEL,
        messages=full_messages,
        tools=TOOLS_SCHEMA,
        tool_choice="auto",
        max_tokens=8096,
        stream=True,
    )
    async for chunk in response:
        yield chunk
```

That is the entire file. No client instantiation, no authentication setup, no response parsing.

## What LiteLLM does for you

Pi.dev builds and maintains 40+ hand-rolled provider adapters in `packages/ai/src/providers/`. Each adapter handles a different provider's authentication scheme, request shape, and streaming event format.

LiteLLM replaces all of that. It:

- Reads `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, etc. from environment variables automatically — no explicit client setup.
- Translates the OpenAI-style request format (including `tools` with `type: "function"` schemas) into whatever format each provider actually expects.
- Normalizes the streaming response from every provider to OpenAI's chunk format, so `agent.py` sees the same `delta.content` / `delta.tool_calls` / `finish_reason` structure regardless of which model is running.

The result: `agent.py` never knows which provider it is talking to. The agent loop is provider-agnostic.

## Swapping providers

Change `MODEL` to change the provider:

| Model string | Provider | Env var needed |
|---|---|---|
| `"claude-sonnet-4-5"` | Anthropic | `ANTHROPIC_API_KEY` |
| `"claude-opus-4-5"` | Anthropic | `ANTHROPIC_API_KEY` |
| `"gemini/gemini-2.0-flash"` | Google | `GEMINI_API_KEY` |
| `"gpt-4o"` | OpenAI | `OPENAI_API_KEY` |
| `"gpt-4o-mini"` | OpenAI | `OPENAI_API_KEY` |

The model string prefix determines the provider. Everything after the prefix is the model name within that provider's namespace. The agent loop code changes nothing.

## Why async

`litellm.acompletion` is the async variant of LiteLLM's completion function. Using it means the coroutine yields control back to the event loop while waiting for each chunk from the network. The event loop can then run other coroutines — specifically, the parallel tool executions in Phase D.

The synchronous variant, `litellm.completion`, blocks the thread. In an async program, a blocking call in one coroutine prevents all other coroutines from running until it returns. That would serialize tool execution: instead of `read_file` and `list_dir` running concurrently, they would run one after the other. It would also block the event loop during the entire streaming response, preventing any other async I/O.

```python
# Do this — non-blocking, event loop stays free
response = await litellm.acompletion(..., stream=True)

# Not this — blocks the thread for the full response duration
response = litellm.completion(..., stream=True)
```

## How the system prompt is injected

`stream_response` prepends the system prompt to `messages` before each call:

```python
full_messages = [{"role": "system", "content": system_prompt}] + messages
```

The `messages` list in `agent.py` only holds the conversation turns (user, assistant, tool). The system prompt is not stored in `messages` — it is injected at the provider boundary. This keeps the history clean and makes it easy to update the system prompt between turns if needed.

## ANTHROPIC_API_KEY from environment

`main.py` calls `load_dotenv()` before `run_agent()`. This reads `.env` at the project root and populates `os.environ`. LiteLLM then reads `ANTHROPIC_API_KEY` (or the relevant provider key) directly from the environment — no explicit configuration needed.

```python
# .env
ANTHROPIC_API_KEY=sk-ant-...
```

```python
# main.py
from dotenv import load_dotenv
load_dotenv()           # loads .env into os.environ
await run_agent(task)   # provider.py picks up the key automatically
```

LiteLLM follows standard environment variable conventions per provider. You do not pass API keys to `acompletion` — it reads them from the environment.

## Tool schemas

`TOOLS_SCHEMA` (imported from `tools.py`) is passed to every `acompletion` call. Each entry uses OpenAI's function-calling format:

```python
{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "...",
        "parameters": {
            "type": "object",
            "properties": { ... },
            "required": ["path"],
        },
    },
}
```

Note: `parameters` not `input_schema`. LiteLLM's standard is OpenAI format. When calling Anthropic, LiteLLM translates `parameters` → `input_schema` internally. You write OpenAI format once; it works everywhere.

`tool_choice="auto"` lets the model decide when to use tools. You can set this to `"required"` to force tool use, or to a specific function name to force one tool — but `"auto"` is correct for a general-purpose coding agent.

## Extending the provider layer

For v1, `provider.py` is intentionally minimal. If you need to extend it:

- **Different max_tokens per task**: pass `max_tokens` as a parameter to `stream_response`.
- **Temperature control**: add a `temperature` parameter; LiteLLM passes it through.
- **Retry on rate limit**: LiteLLM has built-in retry support via `num_retries` parameter.
- **Logging tokens**: `litellm.success_callback` hooks let you capture usage without changing the streaming path.

None of these require touching `agent.py`. The provider boundary keeps the agent loop clean.

## Related pages

- [The Agent Loop](./the-agent-loop.md) — how `stream_response()` is consumed in Phase A
- [Streaming & Event Accumulation](./streaming-and-events.md) — the chunk format that `stream_response()` yields
- [Overview](./overview.md) — where the provider layer fits in the overall system
