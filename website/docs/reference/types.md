---
sidebar_position: 5
title: "types_.py"
description: The core dataclasses — ToolCall, ToolResult, and Message — that flow through the agent loop.
---

# types_.py

`src/types_.py` defines the three dataclasses that carry structured data through the system: `ToolCall`, `ToolResult`, and `Message`. The module is named `types_` (with a trailing underscore) to avoid shadowing the Python standard library's `types` module. See [message types](../architecture/the-agent-loop.md) for how these structures fit into the loop.

:::note
The dataclasses described here reflect the shipped `src/types_.py`.
:::

---

## Dataclasses

### `ToolCall`

```python
@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
```

Represents a single tool invocation requested by the model. The agent loop assembles `ToolCall` instances by parsing the accumulated fragment buffer after the stream ends.

**Fields**

| Field       | Type            | Description                                                                 |
|-------------|-----------------|-----------------------------------------------------------------------------|
| `id`        | `str`           | Unique identifier for this tool call, assigned by the model. Used to correlate the result back to the request. |
| `name`      | `str`           | The tool name to invoke — must match a key in `TOOL_REGISTRY`.              |
| `arguments` | `dict[str, Any]`| Parsed keyword arguments, produced by `json.loads(arguments_buf)` after streaming completes. |

```python
from types_ import ToolCall

call = ToolCall(
    id="call_abc123",
    name="read_file",
    arguments={"path": "src/agent.py", "limit": 100},
)
```

---

### `ToolResult`

```python
@dataclass
class ToolResult:
    tool_call_id: str
    tool_name: str
    content: str
    is_error: bool = False
```

Wraps the string output (or error) from executing one tool call. The agent loop converts `ToolResult` instances into `{"role": "tool", ...}` messages before appending them to the conversation history.

**Fields**

| Field          | Type   | Default | Description                                                              |
|----------------|--------|---------|--------------------------------------------------------------------------|
| `tool_call_id` | `str`  | —       | The `id` from the corresponding `ToolCall`. Links the result to the request in the message history. |
| `tool_name`    | `str`  | —       | The tool that was called. Useful for logging and debugging.              |
| `content`      | `str`  | —       | The tool's output. Always a string — the tool function is responsible for serializing non-string outputs. |
| `is_error`     | `bool` | `False` | Set to `True` when the tool raised an exception or returned an explicit error message. The model can inspect this to decide how to recover. |

```python
from types_ import ToolResult

# Successful result
result = ToolResult(
    tool_call_id="call_abc123",
    tool_name="read_file",
    content="import asyncio\n\nMAX_ITERATIONS = 30\n...",
)

# Error result
error = ToolResult(
    tool_call_id="call_xyz789",
    tool_name="read_file",
    content="Error: file not found: /nonexistent/path.py",
    is_error=True,
)
```

:::tip
`is_error=True` does not terminate the agent. The model receives the error string as the tool's content and can choose to retry with different arguments, try a different tool, or explain the problem to the user.
:::

---

### `Message`

```python
@dataclass
class Message:
    role: str                # "user" | "assistant" | "tool"
    content: str | list | None
```

A thin wrapper around the message dicts that flow through the conversation history. In practice, the agent loop works directly with plain dicts (to stay compatible with the OpenAI message format expected by LiteLLM), but `Message` documents the intended structure.

**Fields**

| Field     | Type                  | Description                                                                     |
|-----------|-----------------------|---------------------------------------------------------------------------------|
| `role`    | `str`                 | `"user"` for user input, `"assistant"` for model turns, `"tool"` for tool result messages (OpenAI convention). |
| `content` | `str \| list \| None` | Plain string for user/tool messages. May be `None` for an assistant turn that only carries tool calls. |

:::info v1 note
In v1, `Message` is primarily for documentation and future type-checking. The agent loop uses plain `dict` objects directly because LiteLLM and the OpenAI message protocol expect dicts. `ToolCall` and `ToolResult` are the actively used dataclasses.
:::

---

## Module name

The file is `types_.py`, not `types.py`. Python's standard library includes a `types` module (containing `FunctionType`, `ModuleType`, etc.). If this file were named `types.py`, any import of `types` in any file under `src/` could resolve to this module instead of stdlib, breaking code that expects `import types` to refer to stdlib.

```python
# Correct import
from types_ import ToolCall, ToolResult, Message

# What you'd accidentally shadow if the file were named types.py
import types  # would resolve to src/types.py, breaking things
```

---

## Related pages

- [agent.py](./agent.md) — creates `ToolResult` instances in `_execute_one_tool`
- [tools.py](./tools.md) — tool functions return `str`; the agent wraps them in `ToolResult`
- [Session Format](./session-format.md) — how `ToolCall` and `ToolResult` map to JSON message shapes
- [The Agent Loop](../architecture/the-agent-loop.md) — narrative explanation of message flow
