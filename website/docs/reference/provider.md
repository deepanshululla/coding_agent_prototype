---
sidebar_position: 3
title: "provider.py"
description: The LiteLLM streaming wrapper — one async generator function that normalizes all providers to OpenAI-format chunks.
---

# provider.py

`src/provider.py` is deliberately thin. It wraps `litellm.acompletion` in a single async generator, `stream_response`, that yields OpenAI-format chunks regardless of which model is configured. Swapping models — from Claude to Gemini to GPT-4o — requires changing one string. See [the provider layer](../architecture/overview.md) for context on why LiteLLM was chosen over a hand-rolled provider abstraction.

:::note
The signatures and behavior described here reflect the shipped `src/provider.py`.
:::

---

## Constants

### `MODEL`

```python
MODEL: str = "claude-sonnet-4-5"
```

The model string passed to `litellm.acompletion`. The prefix selects the provider:

| String prefix        | Provider  | Example                         |
|----------------------|-----------|---------------------------------|
| `claude-*`           | Anthropic | `"claude-sonnet-4-5"`           |
| `gemini/`            | Google    | `"gemini/gemini-2.0-flash"`     |
| `gpt-*`              | OpenAI    | `"gpt-4o"`                      |

Change `MODEL` here to switch providers globally. No other code needs to change.

---

## Functions

### `stream_response`

```python
async def stream_response(
    messages: list[dict],
    system_prompt: str,
) -> AsyncGenerator[Any, None]
```

Async generator that calls `litellm.acompletion` with streaming enabled and yields each chunk as it arrives from the provider.

**Parameters**

| Parameter       | Type         | Description                                                                          |
|-----------------|--------------|--------------------------------------------------------------------------------------|
| `messages`      | `list[dict]` | Conversation history in OpenAI message format. Does **not** include the system message — `stream_response` prepends it internally. |
| `system_prompt` | `str`        | The system prompt string, built by `build_system_prompt()` in `prompts.py`.          |

**Yields** OpenAI-compatible chunk objects. Each chunk has the shape:

```
chunk.choices[0].delta.content          → str | None   (text fragment)
chunk.choices[0].delta.tool_calls       → list | None  (tool call fragments)
  [i].index                             → int          (which tool call slot)
  [i].id                                → str | None   (only on first chunk for that index)
  [i].function.name                     → str | None   (only on first chunk for that index)
  [i].function.arguments                → str          (partial JSON fragment)
chunk.choices[0].finish_reason          → "stop" | "tool_calls" | None
```

**Returns** `None` after the stream is exhausted.

**Raises** Propagates exceptions from `litellm.acompletion` — e.g., `litellm.AuthenticationError` if `ANTHROPIC_API_KEY` is missing or invalid.

---

## How it works

```python
import litellm
from tools import TOOLS_SCHEMA

MODEL = "claude-sonnet-4-5"

async def stream_response(messages: list[dict], system_prompt: str):
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

Key choices:
- `tool_choice="auto"` lets the model decide when to call tools versus when to respond with text.
- `max_tokens=8096` caps each assistant turn. Raise this if the model needs to produce large file writes.
- The system message is prepended here, not passed in by the caller, so callers never accidentally omit it.

---

## Consuming chunks in the agent loop

The agent loop in `agent.py` accumulates tool call fragments by `index` and calls `json.loads` only after the full stream ends:

```python
text_buf = ""
tool_acc: dict[int, dict] = {}   # index → {id, name, arguments_buf}
finish_reason = None

async for chunk in stream_response(messages, system_prompt):
    delta = chunk.choices[0].delta
    finish_reason = chunk.choices[0].finish_reason or finish_reason

    if delta.content:
        text_buf += delta.content
        print(delta.content, end="", flush=True)

    if delta.tool_calls:
        for tc_chunk in delta.tool_calls:
            idx = tc_chunk.index
            if idx not in tool_acc:
                tool_acc[idx] = {"id": "", "name": "", "arguments_buf": ""}
            if tc_chunk.id:
                tool_acc[idx]["id"] = tc_chunk.id
            if tc_chunk.function and tc_chunk.function.name:
                tool_acc[idx]["name"] = tc_chunk.function.name
            if tc_chunk.function and tc_chunk.function.arguments:
                tool_acc[idx]["arguments_buf"] += tc_chunk.function.arguments

# After the stream: json.loads each arguments_buf
```

:::warning
`id` and `name` appear only on the first chunk for each tool call index. Later chunks for the same index have `id=None` and `name=None`. Always guard with `if tc_chunk.id:` before overwriting.
:::

---

## Environment

LiteLLM reads provider credentials from environment variables. No explicit client setup is needed:

| Provider  | Environment variable  |
|-----------|-----------------------|
| Anthropic | `ANTHROPIC_API_KEY`   |
| Google    | `GEMINI_API_KEY`      |
| OpenAI    | `OPENAI_API_KEY`      |

The `.env` file at the repo root is loaded by `main.py` via `python-dotenv` before `run_agent` is called.

---

## Related pages

- [Architecture overview](../architecture/overview.md) — why LiteLLM, not a hand-rolled provider layer
- [agent.py](./agent.md) — the loop that consumes `stream_response`
- [tools.py](./tools.md) — `TOOLS_SCHEMA` passed to `acompletion`
- [prompts.py](./prompts.md) — `build_system_prompt` that produces the `system_prompt` argument
