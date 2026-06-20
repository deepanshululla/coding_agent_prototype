---
sidebar_position: 1
title: Overview
description: What a tool is, the 7 built-in tools at a glance, and how the agent loop dispatches them.
---

# Overview

A tool is the mechanism by which the agent takes action in the world. Without tools, the model can only produce text. With them, it can read files, run shell commands, search codebases, and write new code — all by deciding, mid-response, to call a function you defined.

## What makes up a tool

Every tool in this project has exactly three parts:

1. **A JSON schema dict** — describes the tool to the model: name, purpose, and parameters. This goes into the `tools=` argument of every API call so the model knows what it can request.
2. **An async Python function** — the actual implementation. When the model requests a tool call, the agent loop runs this function with the arguments the model supplied.
3. **An entry in `TOOL_REGISTRY`** — a plain dict mapping tool names (`str`) to their callables. The loop looks up the function by name at dispatch time.

```python
# src/tools.py — the three-part pattern for every tool

async def read_file(path: str, offset: int = 0, limit: int = 2000) -> str:
    ...  # implementation

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file. Use offset/limit for large files.",
            "parameters": { ... },
        },
    },
    # one entry per tool
]

TOOL_REGISTRY: dict[str, callable] = {
    "read_file": read_file,
    # one entry per tool
}
```

:::note
The schema format and registry pattern described here match the shipped `src/tools.py`.
:::

## The 7 built-in tools

| Tool | Purpose |
|---|---|
| `read_file` | Read file contents, with optional line offset and limit |
| `write_file` | Create or overwrite a file with new content |
| `edit_file` | Replace a specific string in an existing file |
| `bash` | Execute any shell command and capture stdout/stderr |
| `grep` | Search for text patterns across files, with line numbers |
| `find_files` | Find files by name pattern (glob), limited to 200 results |
| `list_dir` | List directory contents with file sizes and directory markers |

See [Built-in Tools](./built-in-tools.md) for full parameter and behavior details.

## How the loop dispatches tools

After the model's streaming response completes, the agent loop inspects `finish_reason`. If it is `"tool_calls"`, the loop:

1. Parses each buffered tool call — `id`, `name`, and `arguments` (a JSON string).
2. Calls `_execute_tools_parallel`, which fans all tool calls out concurrently via `asyncio.gather`.
3. Inside `_execute_one_tool`, it looks up the function by name in `TOOL_REGISTRY`. If the name is unknown, it returns an error string immediately without raising.
4. Appends each result as a `{"role": "tool", "tool_call_id": ..., "content": ...}` message to the conversation history.
5. Loops back to send the updated history to the model.

```python
# Dispatch — src/agent.py (simplified)
fn = TOOL_REGISTRY.get(name)
if fn is None:
    return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
result = await fn(**args)
```

The model sees tool results as first-class messages and continues reasoning from them — requesting more tools, refining its approach, or producing a final answer.

## Three things every tool needs

To summarise the contract:

- **A descriptive schema** so the model can decide when and how to call the tool. Vague descriptions cause the model to misuse or ignore the tool.
- **A clean return value** — a `str` in the success case, a descriptive error string (with `is_error=True`) in the failure case. Tools must never raise Python exceptions out to the loop.
- **Registration in `TOOL_REGISTRY`** — a schema without a registry entry, or a registry entry without a schema, produces broken behaviour that's hard to debug.

## Related pages

- [Tool Schema Format](./schema-format.md) — how to write the JSON schema the model reads
- [Built-in Tools](./built-in-tools.md) — parameter reference for all 7 tools
- [Parallel Execution](./parallel-execution.md) — how `asyncio.gather` runs tools concurrently
- [Error Handling](./error-handling.md) — why tools return errors instead of raising them
- [Adding a Tool](./adding-a-tool.md) — step-by-step walkthrough with TDD
