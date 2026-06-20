---
sidebar_position: 4
title: Message Types
description: The ToolCall, ToolResult, and Message dataclasses in types_.py, the exact on-the-wire message shapes, and why tool arguments stay as JSON strings in history.
---

# Message Types

The agent maintains a list of `messages` that grows with every turn. Getting the shape of these messages right is non-negotiable — providers will reject malformed history silently or with cryptic errors. This page covers what the dataclasses look like, what goes into the `messages` list, and a few design choices that differ from pi.dev's richer type hierarchy.

:::note
`src/types_.py` is implemented. The definitions below match the shipped code.
:::

## The dataclasses (`types_.py`)

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

@dataclass
class ToolResult:
    tool_call_id: str
    tool_name: str
    content: str
    is_error: bool = False

@dataclass
class Message:
    role: str                  # "user" | "assistant" | "tool"
    content: str | list | None # str for user/tool, list for assistant, None when only tool calls
```

The module is named `types_` (with a trailing underscore) to avoid shadowing the Python standard library module `types`. Import it as `from types_ import ToolCall, ToolResult`.

`ToolCall` is used internally when dispatching to `TOOL_REGISTRY`. `ToolResult` carries the output (or error) back from each tool execution. `Message` is a lightweight container for history entries — though in practice the `messages` list holds plain dicts in the OpenAI wire format, not `Message` instances, because LiteLLM expects raw dicts.

## On-the-wire message shapes

All three roles in the conversation history have distinct shapes.

### User message

The opening message and any follow-up inputs:

```json
{
    "role": "user",
    "content": "Add type hints to all functions in tools.py"
}
```

Content is a plain string for user messages in v1. (The OpenAI format supports a list of content blocks — text, image — but string content covers all coding tasks.)

### Assistant message

What gets appended after each streaming turn (Phase B of the agent loop):

```json
{
    "role": "assistant",
    "content": "I'll read the file first to understand the current function signatures.",
    "tool_calls": [
        {
            "id": "call_abc123",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": "{\"path\": \"src/tools.py\"}"
            }
        }
    ]
}
```

Key details:
- `content` can be `null` if the model emitted only tool calls with no text.
- `tool_calls` is omitted entirely when the model produced no tool requests.
- `arguments` is a **JSON string**, not a dict. This is OpenAI's wire format and it must be preserved as-is in history.

### Tool result message

One message per tool call result, appended after Phase D (parallel execution):

```json
{
    "role": "tool",
    "tool_call_id": "call_abc123",
    "content": "1  from dataclasses import dataclass\n2  from typing import Any\n..."
}
```

Key details:
- The role is `"tool"`, not `"user"`. (Anthropic's raw format uses `"user"` with a content block of `type: "tool_result"`. LiteLLM handles the translation.)
- One message per result. If the model requested three tools, push three separate `role: "tool"` messages.
- `tool_call_id` ties the result to the specific assistant tool call. The provider uses this to correlate requests and responses.
- `content` is always a string, even for errors. The agent loop does not expose `is_error` to the LLM through the message shape — it just surfaces the error string as content, which the model can reason about.

### A complete two-turn history

```python
messages = [
    # Turn 1: user task
    {"role": "user", "content": "Add type hints to all functions in tools.py"},

    # Turn 2: assistant decides to read the file
    {
        "role": "assistant",
        "content": "Let me read the current content first.",
        "tool_calls": [
            {
                "id": "call_abc",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path": "src/tools.py"}'},
            }
        ],
    },

    # Turn 3: tool result
    {
        "role": "tool",
        "tool_call_id": "call_abc",
        "content": "async def read_file(path: str, ...) -> str:\n    ...",
    },

    # Turn 4: assistant edits the file
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_def",
                "type": "function",
                "function": {
                    "name": "edit_file",
                    "arguments": '{"path": "src/tools.py", "old_string": "async def bash(cmd)", "new_string": "async def bash(cmd: str)"}',
                },
            }
        ],
    },

    # Turn 5: tool result
    {
        "role": "tool",
        "tool_call_id": "call_def",
        "content": "OK — 1 replacement made",
    },

    # Turn 6: assistant wraps up
    {"role": "assistant", "content": "Done. All functions now have type hints.", "tool_calls": None},
]
```

## Why arguments stay as a JSON string

The `arguments` field in an assistant's `tool_calls` entry is always a JSON-encoded string — `'{"path": "src/tools.py"}'` — not a parsed dict. This is OpenAI's wire format, and all LiteLLM-supported providers expect it.

Parsing to a dict happens exactly once, at execution time (Phase D), immediately before calling the tool:

```python
"input": json.loads(tc["function"]["arguments"])
```

Storing the parsed dict in history would break subsequent API calls. Providers deserialize the string themselves and would reject a pre-parsed object in that field.

## Contrast with pi.dev's type hierarchy

Pi uses a much richer type system in TypeScript:

```typescript
// pi.dev types (NOT used here)
type TextContent = { type: "text"; text: string }
type ThinkingContent = { type: "thinking"; thinking: string }
type ImageContent = { type: "image"; source: ... }
type ToolCallContent = { type: "tool_use"; id: string; name: string; input: object }
type ToolResultContent = { type: "tool_result"; tool_use_id: string; content: string }
```

Pi assembles content arrays where each element is typed. This supports images, extended thinking blocks, and multi-modal content mixed in a single message.

For v1 of this project, plain dicts are sufficient. The coding tools return strings, user input is strings, and there are no images. The `Message` dataclass exists to document intent, but the `messages` list is manipulated directly as `list[dict]` to avoid friction with LiteLLM's expected input format.

If you add image support or extended thinking later, migrate the content arrays to typed blocks following pi's pattern. For now, the simpler form keeps the loop readable.

## Related pages

- [The Agent Loop](./the-agent-loop.md) — where messages are appended (Phases B and E)
- [Streaming & Event Accumulation](./streaming-and-events.md) — how raw chunks become finalized tool_calls before going into history
- [The Provider Layer](./provider-layer.md) — how the full `messages` list is passed to LiteLLM
