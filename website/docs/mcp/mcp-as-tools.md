---
sidebar_position: 3
title: MCP Tools in the Loop
description: How each MCP tool is converted into an OpenAI-style schema entry and a registry wrapper, name-collision handling, and an end-to-end walkthrough.
---

# MCP Tools in the Loop

After [connecting to MCP servers](./connecting-servers.md) and calling `list_tools()`, the agent has a list of `Tool` objects. This page covers the adapter that converts each one into the two things the agent loop needs: an entry in `TOOLS_SCHEMA` (so the model knows the tool exists) and an entry in `TOOL_REGISTRY` (so the loop can call it by name).

:::note Status
This is the planned design. v1 ships no MCP client. The adapter pattern described here is the correct extension point — it touches only `TOOLS_SCHEMA` and `TOOL_REGISTRY`; nothing in `src/agent.py` or `src/provider.py` changes.
:::

## Converting an MCP tool to an OpenAI-style schema

An MCP tool descriptor looks like this (from `list_tools()`):

```python
# What the MCP SDK returns
Tool(
    name="read_file",
    description="Read the complete contents of a file from the filesystem.",
    inputSchema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to read",
            }
        },
        "required": ["path"],
    },
)
```

The project's loop expects the OpenAI format (see [Tool Schema Format](../tools/schema-format.md)):

```python
{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "...",
        "parameters": { ... },   # same content as inputSchema
    },
}
```

The conversion is a direct structural mapping — `inputSchema` becomes `parameters`, wrapped in the `{"type": "function", "function": {...}}` envelope:

```python
# src/mcp_client.py (planned)
def _mcp_tool_to_schema(tool, registered_name: str) -> dict:
    """Convert an MCP Tool descriptor to the project's OpenAI-style schema dict."""
    return {
        "type": "function",
        "function": {
            "name": registered_name,
            "description": tool.description or "",
            "parameters": tool.inputSchema,
        },
    }
```

`registered_name` may differ from `tool.name` when a name-collision prefix has been applied (see below).

## Registering a dispatch wrapper

The registry entry is a thin async function that:

1. Calls `session.call_tool(name, args)` on the MCP session.
2. Flattens the MCP result content blocks to a plain string.
3. Returns the string. On any error, returns `"Error: ..."` — tools never raise.

```python
# src/mcp_client.py (planned)
def _make_mcp_wrapper(session, tool_name: str):
    """Return an async callable that forwards a tool call to the MCP server."""

    async def wrapper(**kwargs) -> str:
        try:
            result = await session.call_tool(tool_name, kwargs)
        except Exception as e:
            return f"Error calling MCP tool '{tool_name}': {e}"

        # result.content is a list of content blocks (TextContent, ImageContent, etc.)
        # Flatten to a single string; non-text blocks are noted but not rendered.
        parts: list[str] = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(f"[{block.type} content omitted]")

        if result.isError:
            return "Error: " + "\n".join(parts)
        return "\n".join(parts) or "(empty result)"

    return wrapper
```

The wrapper signature is `**kwargs` — it accepts whatever keyword arguments the model passes, matching the parameter names from the schema. The `call_tool` method forwards them as a dict to the MCP server's `tools/call` handler.

## Registering all tools from a server

The `_register_mcp_tools` function wires both pieces together:

```python
# src/mcp_client.py (planned)
from tools import TOOLS_SCHEMA, TOOL_REGISTRY

def _register_mcp_tools(session, server_name: str, tools) -> None:
    """Append schemas and register wrappers for all tools from one MCP server."""
    for tool in tools:
        registered_name = _resolve_name(tool.name, server_name)
        schema = _mcp_tool_to_schema(tool, registered_name)
        TOOLS_SCHEMA.append(schema)
        TOOL_REGISTRY[registered_name] = _make_mcp_wrapper(session, tool.name)
```

After this runs, the model's next API call includes the extended `TOOLS_SCHEMA` list. The loop dispatches by name exactly as it would for a built-in.

## Name-collision handling

MCP tool names are chosen by the server authors. A filesystem server and a built-in might both want the name `read_file`. A collision in `TOOL_REGISTRY` would silently override the built-in.

The resolution rule: **prefix with the server name and double underscore** when a name already exists in `TOOL_REGISTRY`.

```python
def _resolve_name(tool_name: str, server_name: str) -> str:
    """Return a registered name, prefixing with server_name__ if there's a collision."""
    if tool_name not in TOOL_REGISTRY:
        return tool_name
    prefixed = f"{server_name}__{tool_name}"
    return prefixed
```

Examples with a server named `"fs"`:

| MCP tool name | Built-in? | Registered as |
|---|---|---|
| `search_repositories` | No | `search_repositories` |
| `read_file` | Yes | `fs__read_file` |
| `list_directory` | No | `list_directory` |

The prefixed name is what goes into both the schema (`"name": "fs__read_file"`) and the registry key. The model sees `fs__read_file` in the schema and calls it by that name. The wrapper still calls `session.call_tool("read_file", ...)` — it uses the original MCP name on the server side.

:::tip
Choose descriptive server names in `mcp.json`. They appear as tool-name prefixes when there are collisions, so `"fs"`, `"github"`, and `"pg"` are more readable in the model's output than `"server1"` or `"mcp1"`.
:::

## End-to-end walkthrough

Here is what happens from config to tool result, step by step.

**1. Config and startup**

`mcp.json` declares a filesystem server:

```json
{
  "mcpServers": {
    "fs": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"]
    }
  }
}
```

`AGENT_MCP_CONFIG=./mcp.json python main.py "read the README"` is run.

**2. Discovery**

`load_mcp_servers()` starts the subprocess, opens a `ClientSession`, calls `initialize()`, then `list_tools()`. The server reports a tool named `read_file`.

Because `read_file` is already in `TOOL_REGISTRY` (it's a built-in), it is registered as `fs__read_file`. Its schema is appended to `TOOLS_SCHEMA`.

**3. Model sees the tool**

The first API call includes the extended `TOOLS_SCHEMA`. The model sees both the built-in `read_file` and `fs__read_file`. For a task like "read the README", it may choose the built-in (relative path) or the MCP version (controlled access path) depending on the descriptions.

**4. Model calls the MCP tool**

The model requests `fs__read_file` with `{"path": "/home/user/projects/README.md"}`.

**5. Dispatch**

`_execute_one_tool` looks up `"fs__read_file"` in `TOOL_REGISTRY`, finds the wrapper, and calls it with `path="/home/user/projects/README.md"`.

**6. MCP call**

The wrapper calls `session.call_tool("read_file", {"path": "/home/user/projects/README.md"})`. The MCP server reads the file and returns a `TextContent` block.

**7. Result in history**

The wrapper flattens the content block to a string and returns it. The loop appends:

```python
{"role": "tool", "tool_call_id": "...", "content": "# My Project\n\nThis is the README."}
```

The model continues reasoning from this result, just as it would for a built-in tool call.

## Security note

MCP servers are external processes running arbitrary code. An MCP filesystem server can read and write files beyond the agent's working directory. An MCP GitHub server can open issues and push code. These are the same class of risks as the `bash` tool — and in some cases wider, because the server may have persistent credentials or broader filesystem access than the agent process itself.

**Apply the same operating posture you would for `bash`:**

- Run in a container with a scoped mount. See [Security Model](../operations/security.md).
- Scope the MCP server's access at the server level (e.g., pass only the project directory to the filesystem server, not `/`).
- Don't connect to MCP servers you don't control or haven't reviewed, especially when working with untrusted input. A prompt-injected tool result from one server could instruct the model to misuse another server's tools.
- Consider adding a permission gate in `_execute_one_tool` that requires human approval before any MCP tool call executes, just as you might for `bash`. See [Command Allowlist](../operations/command-allowlist.md) for the gating pattern.

:::danger
An MCP server that has write access to your filesystem or codebase, combined with an untrusted task or a prompt injection, can cause the same damage as an unconstrained `bash` call. Scope access tightly.
:::

## Related pages

- [Overview](./overview.md) — the big picture of MCP integration
- [Connecting Servers](./connecting-servers.md) — the config file and session startup
- [Tool Overview](../tools/overview.md) — the three-part contract this adapter satisfies
- [Tool Schema Format](../tools/schema-format.md) — the OpenAI-style schema MCP tools are converted to
- [Error Handling](../tools/error-handling.md) — why wrappers return error strings instead of raising
- [Security Model](../operations/security.md) — operating posture for external tools
- [Command Allowlist](../operations/command-allowlist.md) — the gating pattern to apply to MCP tool calls
