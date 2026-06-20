---
sidebar_position: 5
title: Error Handling
description: Why tools return error strings instead of raising exceptions, and how the loop handles unknown tools.
---

# Error Handling

The single most important rule for tools in this project: **a tool must never raise a Python exception out to the agent loop**. Instead, it returns a descriptive error string and signals failure via `is_error=True` on the `ToolResult`.

## Why return errors instead of raising

When a tool raises an unhandled exception, the agent loop crashes or the error gets silently swallowed — neither outcome is useful. The model gets no information about what went wrong, can't reason about the failure, and can't try an alternative approach.

When a tool returns an error string, the loop packages it as a normal tool result and sends it back to the model in the conversation history. The model reads the error, understands what happened, and responds. It might:

- Retry with corrected arguments
- Try a different tool
- Ask the user for clarification
- Report that the task isn't possible in its current state

This is the "agent resilience" pattern from pi.dev's design. The model is the error handler; your job is to give it accurate information.

## The try/except in `_execute_one_tool`

The loop wraps every tool dispatch in a try/except as a final safety net:

```python
async def _execute_one_tool(tool_call: dict) -> ToolResult:
    name = tool_call["name"]
    args = tool_call["input"]
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
    try:
        result = await fn(**args)
    except Exception as e:
        return ToolResult(tool_call["id"], name, f"Error: {e}", is_error=True)
    return ToolResult(tool_call["id"], name, result)
```

The `except Exception` block is a backstop, not the primary mechanism. Individual tool functions should catch their own errors and return informative strings rather than letting exceptions bubble up. The loop-level catch exists because tool authors are human — it ensures one buggy tool can't crash the entire agent session.

## Unknown tool handling

If the model requests a tool that isn't in `TOOL_REGISTRY` — a hallucinated tool name, a tool that was removed, a typo — the loop handles it immediately before calling any function:

```python
fn = TOOL_REGISTRY.get(name)
if fn is None:
    return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
```

The model sees `"Unknown tool: some_tool_name"` in the result and can adjust. In practice this happens rarely if your tool schemas are consistent with `TOOL_REGISTRY`, but it's an important guard against schema/registry drift.

## What good error strings look like

A good error string answers: what went wrong, and what would help fix it?

| Situation | Bad error | Good error |
|---|---|---|
| File not found | `"Error"` | `"File not found: /src/utils.py"` |
| `old_string` missing | `"Edit failed"` | `"old_string not found in /src/tools.py — read the file and verify the exact text"` |
| `old_string` not unique | `"Multiple matches"` | `"old_string matches 3 locations in /src/tools.py — provide more surrounding context to make it unique"` |
| Subprocess timeout | `"Timed out"` | `"Command timed out after 30s: pytest tests/ — try running a specific test file instead"` |
| Permission denied | `"Cannot write"` | `"Permission denied writing to /etc/hosts — choose a path inside the project directory"` |

The pattern is: name the tool that failed, describe the specific condition, and where possible suggest what to try next.

## `is_error` and message history

`ToolResult.is_error` is a flag on the dataclass:

```python
@dataclass
class ToolResult:
    tool_call_id: str
    tool_name: str
    content: str
    is_error: bool = False
```

The current loop sends the `content` string to the model regardless of `is_error`. The flag is available for future use — for example, a `beforeToolCall`/`afterToolCall` hook system could use it to decide whether to surface failures to the user, log them, or trigger a retry policy. For now, the model's own reasoning serves as the retry mechanism.

## What not to do

```python
# Wrong — raises on file not found, crashes the loop
async def read_file(path: str) -> str:
    return Path(path).read_text()   # FileNotFoundError propagates

# Right — returns an error the model can act on
async def read_file(path: str) -> str:
    try:
        return Path(path).read_text()
    except FileNotFoundError:
        return f"File not found: {path}"
    except PermissionError:
        return f"Permission denied reading: {path}"
    except Exception as e:
        return f"Error reading {path}: {e}"
```

:::warning
Catching `Exception` broadly inside tools is acceptable here because you are always re-raising as a return value, not swallowing the error silently. The model sees the exception message and can reason from it.
:::

## Related pages

- [Overview](./overview.md) — how tool results flow back into the conversation
- [Parallel Execution](./parallel-execution.md) — how failures in one task don't block others
- [Adding a Tool](./adding-a-tool.md) — includes error handling in the step-by-step guide
