---
sidebar_position: 7
title: "Session Format"
description: The JSON shape of the messages list — user turns, assistant turns with tool calls, and tool result turns.
---

# Session Format

The agent's entire conversational state is a single `list[dict]` called `messages`. Every message in the list has a `role` and `content`; assistant turns that requested tool calls additionally carry a `tool_calls` array. Tool results arrive as their own messages with `role: "tool"`.

This format follows the OpenAI message protocol, which is what LiteLLM normalizes all providers to. Understanding the exact JSON shapes is important if you want to inspect, replay, or test the agent's behavior. See [concepts/sessions](../concepts/context-window.md) for more on context management.

:::note
Persistence (saving and loading `messages` to disk) is not implemented in v1. The session exists only in memory for the duration of one `run_agent` call.
:::

---

## Message shapes

### User message

```json
{
  "role": "user",
  "content": "add type hints to all functions in tools.py"
}
```

| Field     | Type     | Description                                                 |
|-----------|----------|-------------------------------------------------------------|
| `role`    | `"user"` | Always `"user"`.                                            |
| `content` | `str`    | The user's task or follow-up message, as a plain string.    |

---

### Assistant message (text only)

When the model responds with text and no tool calls:

```json
{
  "role": "assistant",
  "content": "I'll start by reading the current contents of tools.py."
}
```

| Field     | Type          | Description                                         |
|-----------|---------------|-----------------------------------------------------|
| `role`    | `"assistant"` | Always `"assistant"`.                               |
| `content` | `str \| null` | The model's text response. `null` when the model only calls tools and produces no text. |

---

### Assistant message (with tool calls)

When the model requests one or more tool calls:

```json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [
    {
      "id": "call_abc123",
      "type": "function",
      "function": {
        "name": "read_file",
        "arguments": "{\"path\": \"src/tools.py\", \"limit\": 50}"
      }
    },
    {
      "id": "call_xyz789",
      "type": "function",
      "function": {
        "name": "list_dir",
        "arguments": "{\"path\": \"src/\"}"
      }
    }
  ]
}
```

| Field                              | Type            | Description                                                                     |
|------------------------------------|-----------------|---------------------------------------------------------------------------------|
| `role`                             | `"assistant"`   | Always `"assistant"`.                                                           |
| `content`                          | `str \| null`   | Text accompanying the tool calls, or `null`.                                    |
| `tool_calls`                       | `list`          | One entry per tool call requested in this turn.                                 |
| `tool_calls[i].id`                 | `str`           | Unique call ID. The matching tool result must reference this `id`.              |
| `tool_calls[i].type`               | `"function"`    | Always `"function"` in OpenAI format.                                           |
| `tool_calls[i].function.name`      | `str`           | Tool name — must match a key in `TOOL_REGISTRY`.                                |
| `tool_calls[i].function.arguments` | `str`           | JSON-encoded arguments **as a string**, not a parsed object. Providers expect the string form in message history. |

:::warning arguments stays a string
`function.arguments` is always stored as a JSON string in the message history — even after the stream ends. The agent loop calls `json.loads(arguments)` to get the dict it passes to the tool function, but the string form is what gets appended to `messages`. Providers reject a dict here.
:::

---

### Tool result message

Each tool result is its own message with `role: "tool"`. One result message per tool call — results are never batched:

```json
{
  "role": "tool",
  "tool_call_id": "call_abc123",
  "content": "import asyncio\nimport json\nfrom provider import stream_response\n..."
}
```

| Field          | Type     | Description                                                                         |
|----------------|----------|-------------------------------------------------------------------------------------|
| `role`         | `"tool"` | Always `"tool"`.                                                                    |
| `tool_call_id` | `str`    | Must match the `id` of the corresponding `tool_calls` entry in the assistant turn. |
| `content`      | `str`    | The tool's string output, or an error message string if `is_error` was `True`.      |

---

## Annotated full example

A complete exchange where the agent reads a file and then reports back:

```json
[
  {
    "role": "user",
    "content": "How many lines does src/agent.py have?"
  },
  {
    "role": "assistant",
    "content": "Let me check the file.",
    "tool_calls": [
      {
        "id": "call_001",
        "type": "function",
        "function": {
          "name": "bash",
          "arguments": "{\"command\": \"wc -l src/agent.py\"}"
        }
      }
    ]
  },
  {
    "role": "tool",
    "tool_call_id": "call_001",
    "content": "      87 src/agent.py"
  },
  {
    "role": "assistant",
    "content": "src/agent.py has 87 lines."
  }
]
```

**What this shows:**
1. User asks a question (turn 1).
2. Assistant decides to call `bash` to count lines; includes some text alongside the tool call (turn 2).
3. Tool result comes back as its own `role: "tool"` message referencing `call_001` (turn 3).
4. Assistant reads the result and answers in a final text turn (turn 4).

---

## Multi-tool turn example

When the model calls two tools in one turn, both results are appended before the next assistant turn:

```json
[
  {
    "role": "user",
    "content": "What files are in src/ and what does agent.py import?"
  },
  {
    "role": "assistant",
    "content": null,
    "tool_calls": [
      {
        "id": "call_A",
        "type": "function",
        "function": {
          "name": "list_dir",
          "arguments": "{\"path\": \"src/\"}"
        }
      },
      {
        "id": "call_B",
        "type": "function",
        "function": {
          "name": "read_file",
          "arguments": "{\"path\": \"src/agent.py\", \"limit\": 10}"
        }
      }
    ]
  },
  {
    "role": "tool",
    "tool_call_id": "call_A",
    "content": "agent.py  (file, 3421 bytes)\ntools.py  (file, 5102 bytes)\n..."
  },
  {
    "role": "tool",
    "tool_call_id": "call_B",
    "content": "import asyncio\nimport json\nfrom provider import stream_response\n..."
  },
  {
    "role": "assistant",
    "content": "src/ contains agent.py, tools.py, prompts.py, provider.py, and types_.py. agent.py imports asyncio, json, and stream_response from provider."
  }
]
```

Both `call_A` and `call_B` are executed in parallel by `_execute_tools_parallel`, then appended to `messages` in order before the next call to `stream_response`.

---

## Persistence (v1 limitation)

In v1, `messages` is a plain Python list that lives for the duration of one `run_agent` call. When the process exits, the session is gone. To add persistence:

1. Serialize `messages` to JSON after each inner-loop iteration: `json.dump(messages, open("session.json", "w"))`
2. Load on startup: `messages = json.load(open("session.json"))` if the file exists

The format is already JSON-serializable (all values are strings, lists, or dicts) — no additional transformation needed.

---

## Related pages

- [agent.py](./agent.md) — builds and mutates the `messages` list in the loop
- [types_.py](./types.md) — `ToolCall` and `ToolResult` dataclasses that mirror these JSON shapes
- [Context window](../concepts/context-window.md) — how the messages list affects token usage
- [provider.py](./provider.md) — receives `messages` and prepends the system message before sending
