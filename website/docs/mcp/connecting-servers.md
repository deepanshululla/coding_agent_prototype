---
sidebar_position: 2
title: Connecting Servers
description: The mcp.json config shape, how the agent opens a ClientSession per server at startup, and session lifecycle.
---

# Connecting Servers

The agent discovers MCP servers from a JSON config file pointed to by `AGENT_MCP_CONFIG`. It opens one `ClientSession` per server at startup, calls `list_tools()` to enumerate available tools, and holds the connections open for the lifetime of the process.

:::note Status
This is the planned design. v1 ships no MCP client. The integration point — appending to `TOOLS_SCHEMA` and `TOOL_REGISTRY` before the agent loop starts — is well-defined in `src/tools.py` and `src/agent.py`.
:::

## The config file

The config file mirrors the `mcpServers` shape used by Claude Desktop and many other MCP clients. This means server configs you already have for other tools usually work here without modification.

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"],
      "env": {}
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "<your-token>"
      }
    },
    "analytics-api": {
      "url": "http://localhost:8080/mcp"
    }
  }
}
```

### Stdio servers

A stdio server is a subprocess. The agent launches it and communicates over its stdin/stdout. Required fields:

| Field | Type | Description |
|---|---|---|
| `command` | string | The executable to run (`npx`, `python`, `node`, etc.) |
| `args` | string[] | Arguments passed to the command |
| `env` | object | Extra environment variables for the subprocess (merged with the agent's own env) |

Most MCP servers from the official ecosystem use `npx -y <package>` as the command. The `-y` flag skips the npm install prompt.

### HTTP/SSE servers

A remote server is identified by a URL. The agent connects using the MCP streamable HTTP transport. Required field:

| Field | Type | Description |
|---|---|---|
| `url` | string | The base URL of the MCP server (e.g., `http://localhost:8080/mcp`) |

HTTP servers are useful for servers that maintain shared state (a database connection pool, a running browser instance) or servers that run on a different machine.

## Startup sequence

Before `run_agent` is called, the MCP startup routine runs once:

```python
# src/mcp_client.py (planned)
import json
import os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from tools import TOOLS_SCHEMA, TOOL_REGISTRY

async def load_mcp_servers() -> list[ClientSession]:
    config_path = os.environ.get("AGENT_MCP_CONFIG")
    if not config_path:
        return []

    with open(config_path) as f:
        config = json.load(f)

    sessions: list[ClientSession] = []

    for server_name, server_cfg in config.get("mcpServers", {}).items():
        if "url" in server_cfg:
            # HTTP/SSE transport
            transport = await streamablehttp_client(server_cfg["url"])
        else:
            # stdio transport
            params = StdioServerParameters(
                command=server_cfg["command"],
                args=server_cfg.get("args", []),
                env={**os.environ, **server_cfg.get("env", {})},
            )
            transport = await stdio_client(params)

        read, write = transport
        session = ClientSession(read, write)
        await session.initialize()

        tools_result = await session.list_tools()
        _register_mcp_tools(session, server_name, tools_result.tools)
        sessions.append(session)

    return sessions
```

`load_mcp_servers()` is called once at the top of `main.py`, before the agent loop starts. The returned sessions are closed in a `finally` block when the process exits.

### What `initialize()` does

`initialize()` performs the MCP handshake: the client sends its capabilities and protocol version, the server responds with its own. The session is not usable until `initialize()` completes. Always await it before calling `list_tools()` or `call_tool()`.

### What `list_tools()` returns

`list_tools()` returns a list of `Tool` objects. Each has:

- `name` — the tool's identifier (e.g., `"read_file"`, `"search_repositories"`)
- `description` — a human-readable explanation
- `inputSchema` — a JSON Schema object for the tool's parameters (the MCP equivalent of `"parameters"` in the OpenAI schema)

The adapter in [MCP Tools in the Loop](./mcp-as-tools.md) converts each of these into the project's schema format and registers a dispatch wrapper.

## Session lifecycle

Sessions are opened at startup and held open until shutdown. The pattern in `main.py`:

```python
# main.py (planned)
import asyncio
from mcp_client import load_mcp_servers
from agent import run_agent

async def main():
    sessions = await load_mcp_servers()
    try:
        await run_agent(task=input("> "))
    finally:
        for session in sessions:
            await session.aclose()

asyncio.run(main())
```

Holding sessions open matters for stdio servers: each connection is a running subprocess. Opening and closing a subprocess on every tool call would add hundreds of milliseconds of latency and waste process startup overhead. For HTTP servers it is a persistent HTTP connection.

### Event loop compatibility

The `mcp` SDK is fully async. The sessions share the same `asyncio` event loop as the agent. No threading is needed and no extra event loop is created. The stdio transport creates a subprocess managed by asyncio's subprocess support (`asyncio.create_subprocess_exec`), which is compatible with `asyncio.to_thread` used by the built-in tools.

## Verifying connections at startup

If a server fails to start (wrong command, missing package, network error), `initialize()` will raise. The recommended approach is to let that propagate and abort startup with a clear error message rather than silently omitting the server:

```python
try:
    await session.initialize()
except Exception as e:
    raise RuntimeError(
        f"Failed to connect to MCP server '{server_name}': {e}"
    ) from e
```

This surfaces misconfigured servers immediately rather than puzzling over why a tool the model tried to call returns "Unknown tool".

## Related pages

- [Overview](./overview.md) — how MCP tools integrate with the agent loop
- [MCP Tools in the Loop](./mcp-as-tools.md) — converting discovered tools into schemas and registry wrappers
- [Settings Reference](../operations/settings.md) — `AGENT_MCP_CONFIG` and other environment variables
- [Security Model](../operations/security.md) — trust model for external MCP servers
