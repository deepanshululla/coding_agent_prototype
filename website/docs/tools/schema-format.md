---
sidebar_position: 2
title: Tool Schema Format
description: How to write OpenAI-style tool schemas that LiteLLM translates to any provider.
---

# Tool Schema Format

Every tool has a JSON schema that tells the model what the tool does and how to call it. Getting this right matters: the model reads your description and parameter names to decide when to use a tool and what arguments to pass.

## OpenAI format, not Anthropic format

This project uses LiteLLM as its provider layer. LiteLLM expects **OpenAI-style** tool schemas and translates them internally to whatever format the underlying provider requires — Anthropic, Google, Mistral, and so on.

The key distinction:

| Field | OpenAI / LiteLLM format | Anthropic native format |
|---|---|---|
| Outer wrapper | `{"type": "function", "function": {...}}` | `{"name": ..., "description": ..., "input_schema": {...}}` |
| Parameters key | `"parameters"` | `"input_schema"` |

Always use `"parameters"`, not `"input_schema"`. If you use the Anthropic format directly, LiteLLM will misroute the schema when you switch to a non-Anthropic model.

:::tip
Swapping models is the whole point of using LiteLLM. Write schemas once in OpenAI format and they work with `"claude-sonnet-4-5"`, `"gemini/gemini-2.0-flash"`, and `"gpt-4o"` without any changes.
:::

## Annotated example: `read_file`

The `read_file` schema in `TOOLS_SCHEMA` is a good template. Every field serves a purpose.

```python
{
    "type": "function",           # Required outer wrapper — always "function"
    "function": {
        "name": "read_file",      # Must match the key in TOOL_REGISTRY exactly
        "description": (          # The model reads this to decide when to call the tool.
            "Read the contents of a file. "
            "Use offset/limit for large files."
        ),
        "parameters": {           # "parameters", not "input_schema"
            "type": "object",     # Always "object" at the top level
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path to read",   # Per-parameter description
                },
                "offset": {
                    "type": "integer",
                    "description": "Line to start from (0-indexed)",
                    "default": 0,                          # Hint to the model; not enforced by API
                },
                "limit": {
                    "type": "integer",
                    "description": "Max lines to return",
                    "default": 2000,
                },
            },
            "required": ["path"],  # Only truly mandatory params go here
        },
    },
}
```

## Properties, required, and defaults

**`properties`** is a dict of parameter name → JSON Schema object. Each parameter needs at minimum a `"type"`. Adding a `"description"` is strongly recommended — it is the primary signal the model uses when deciding what value to pass.

**`"required"`** is a list of parameter names the model must always provide. Leave optional parameters out of `required` and give them a `"default"` in the schema description instead. The API does not enforce defaults — your Python function must handle missing arguments with Python default values.

```python
# The schema says offset is optional with default 0
# The function enforces it
async def read_file(path: str, offset: int = 0, limit: int = 2000) -> str:
    ...
```

**Supported JSON Schema types** for parameters: `"string"`, `"integer"`, `"number"`, `"boolean"`, `"array"`, `"object"`. Keep parameters simple — deeply nested objects make it harder for the model to fill them in correctly.

## Why descriptions matter

The model has no ability to inspect your Python function at runtime. The only information it gets about a tool is the schema you send with every API call. A parameter named `path` with no description leaves the model guessing — does it want an absolute path? Relative? A URL?

Write descriptions as if you were writing a docstring for a colleague who will never see the implementation:

- `"File path to read"` — minimal but clear
- `"Absolute or relative path to the file. Relative paths resolve from the agent's working directory."` — better for a production tool

A well-described tool gets called correctly the first time. A poorly described one leads to tool call errors, extra round-trips, and wasted tokens.

:::note
Description quality directly affects how reliably the model uses a tool. In practice, bad descriptions are a more common source of agent failures than bugs in the implementation.
:::

## Where schemas live in the codebase

All schemas are collected in `TOOLS_SCHEMA` (a list) in `src/tools.py`. The provider layer passes this list unchanged to `litellm.acompletion`:

```python
# src/provider.py
response = await litellm.acompletion(
    model=MODEL,
    messages=full_messages,
    tools=TOOLS_SCHEMA,      # The full list, every call
    tool_choice="auto",
    ...
)
```

`tool_choice="auto"` lets the model decide whether to call a tool on each turn. The model can also call zero tools (produce a final answer) or call multiple tools in one turn.

## Related pages

- [Overview](./overview.md) — the three-part tool contract
- [Built-in Tools](./built-in-tools.md) — schemas for all 7 tools
- [Adding a Tool](./adding-a-tool.md) — write a new schema from scratch
