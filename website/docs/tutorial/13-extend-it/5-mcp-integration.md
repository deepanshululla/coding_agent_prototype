---
sidebar_position: 5
title: "Layer 13.5 — MCP Integration"
description: Connect MCP servers via AGENT_MCP_CONFIG and merge their tools into TOOLS_SCHEMA / TOOL_REGISTRY so they are callable exactly like the 7 built-ins.
---

# Layer 13.5 — MCP Integration

:::note Implemented
This step is implemented on branch `step/phase-13-5-mcp-integration` (plan: `plans/tutorial/phase-13-5-mcp-integration.md`).
:::

:::note Starting point
Layer 13.4 complete: Agent Skills are installed and loaded on demand via `load_skill`. The test suite passes.
:::

The 7 built-in tools cover the core coding-agent workflow. But they can't query a database, search GitHub, or control a browser. Adding those capabilities as Python tools means writing implementation code for each one.

The Model Context Protocol (MCP) gives you a better path: connect to an external server that already implements those tools, convert its schema descriptors into the format the loop expects, and register thin dispatch wrappers. The agent loop never changes — it still calls `TOOL_REGISTRY[name](**args)` — and the model sees MCP tools through `TOOLS_SCHEMA` exactly as it sees the built-ins.

The full design is in [MCP Overview](../../mcp/overview.md). The config format and startup sequence are in [Connecting Servers](../../mcp/connecting-servers.md). The adapter — converting MCP descriptors to schema entries and registry wrappers — is in [MCP Tools in the Loop](../../mcp/mcp-as-tools.md).

## What you'll learn

- The `mcp.json` config shape and how `AGENT_MCP_CONFIG` enables it.
- The startup sequence: `initialize()` → `list_tools()` → append to `TOOLS_SCHEMA` → register wrappers in `TOOL_REGISTRY`.
- The name-collision rule: prefix with `<server>__` when a name already exists.
- How the agent loop dispatches an MCP tool call identically to a built-in call.
- Why the result appears as a standard `role: "tool"` message.

## Build it

### Step 1 — Create `src/mcp_client.py`

```python
# src/mcp_client.py
"""MCP client: discover servers, adapt their tools, merge into TOOLS_SCHEMA/TOOL_REGISTRY."""

from __future__ import annotations

import json
import os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from tools import TOOLS_SCHEMA, TOOL_REGISTRY


# ── Schema conversion ────────────────────────────────────────────────────────

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


# ── Name-collision resolution ─────────────────────────────────────────────────

def _resolve_name(tool_name: str, server_name: str) -> str:
    """Return a registry key, prefixing with server_name__ on collision."""
    if tool_name not in TOOL_REGISTRY:
        return tool_name
    return f"{server_name}__{tool_name}"


# ── Dispatch wrapper ─────────────────────────────────────────────────────────

def _make_mcp_wrapper(session: ClientSession, tool_name: str):
    """Return an async callable that forwards a tool call to the MCP server."""

    async def wrapper(**kwargs) -> str:
        try:
            result = await session.call_tool(tool_name, kwargs)
        except Exception as e:
            return f"Error calling MCP tool '{tool_name}': {e}"

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


# ── Registration ──────────────────────────────────────────────────────────────

def _register_mcp_tools(session: ClientSession, server_name: str, tools) -> None:
    """Append schemas and register wrappers for all tools from one MCP server."""
    for tool in tools:
        registered_name = _resolve_name(tool.name, server_name)
        TOOLS_SCHEMA.append(_mcp_tool_to_schema(tool, registered_name))
        TOOL_REGISTRY[registered_name] = _make_mcp_wrapper(session, tool.name)


# ── Startup ───────────────────────────────────────────────────────────────────

async def load_mcp_servers() -> list[ClientSession]:
    """
    Read AGENT_MCP_CONFIG, connect to each server, and register their tools.
    Returns the open sessions (caller must close them on exit).
    """
    config_path = os.environ.get("AGENT_MCP_CONFIG")
    if not config_path:
        return []

    with open(config_path) as f:
        config = json.load(f)

    sessions: list[ClientSession] = []

    for server_name, server_cfg in config.get("mcpServers", {}).items():
        if "url" in server_cfg:
            transport = await streamablehttp_client(server_cfg["url"])
        else:
            params = StdioServerParameters(
                command=server_cfg["command"],
                args=server_cfg.get("args", []),
                env={**os.environ, **server_cfg.get("env", {})},
            )
            transport = await stdio_client(params)

        read, write = transport
        session = ClientSession(read, write)
        try:
            await session.initialize()
        except Exception as e:
            raise RuntimeError(
                f"Failed to connect to MCP server '{server_name}': {e}"
            ) from e

        tools_result = await session.list_tools()
        _register_mcp_tools(session, server_name, tools_result.tools)
        sessions.append(session)

    return sessions
```

### Step 2 — Call `load_mcp_servers` from `main.py`

```python
# main.py (updated)
import asyncio
import os
import sys

from src.agent import run_agent
from src.mcp_client import load_mcp_servers
from src.project_instructions import load_project_instructions
from src.prompts import build_system_prompt


async def main() -> None:
    task = " ".join(sys.argv[1:]) or input("Task: ")
    cwd = os.getcwd()

    # MCP servers must be loaded before run_agent — they mutate TOOLS_SCHEMA/TOOL_REGISTRY
    sessions = await load_mcp_servers()
    try:
        extra = load_project_instructions(cwd)
        system_prompt = build_system_prompt(cwd=cwd, extra=extra)
        await run_agent(task, system_prompt=system_prompt)
    finally:
        for session in sessions:
            await session.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

`load_mcp_servers()` must run *before* `build_system_prompt` is called — not because the prompt uses the tool names directly, but so `TOOLS_SCHEMA` is fully populated before the first API call includes it.

### Step 3 — Create a minimal `mcp.json`

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
      "env": {}
    }
  }
}
```

```bash
AGENT_MCP_CONFIG=./mcp.json uv run main.py "read README.md using the filesystem MCP server"
```

:::tip Name collisions in practice
The filesystem server exports a `read_file` tool. Because `read_file` is already in `TOOL_REGISTRY` (built-in), it is registered as `filesystem__read_file`. The model sees both names in the schema and chooses based on descriptions. Choose descriptive server names in `mcp.json` — they appear as prefixes.
:::

:::danger MCP servers run external code
An MCP filesystem server can read and write files beyond the working directory. Apply the same operating posture as the `bash` tool: run in a container, scope server access tightly, and never connect to servers from untrusted sources. See [Security Model](../../operations/security.md).
:::

## Test it

### Behavior (BDD)

Verify this layer as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Scenario: MCP tool appears in the registry, is called by the model, and returns a tool message
  Given AGENT_MCP_CONFIG points to a config with a running MCP server
  And that server exposes a tool named "list_directory"
  When load_mcp_servers() is called at startup
  Then "list_directory" (or "server__list_directory" if collision) is in TOOL_REGISTRY
  And TOOLS_SCHEMA contains an entry with that tool's name and description
  When the agent processes a task that causes the model to call "list_directory"
  Then the message history contains a message with role "tool"
       and content matching the server's response
  And the result is indistinguishable from a built-in tool result
```

Run this as an integration scenario with the [BDD framework](../../guides/bdd-integration-testing.md).

The scenario fails before the change because `load_mcp_servers` does not exist, the MCP tool is absent from `TOOL_REGISTRY`, and any model attempt to call it returns `"Unknown tool"`. After the change, the full dispatch cycle completes and produces the expected `role: "tool"` message.

### Existing tests

```bash
uv run pytest -q
```

When `AGENT_MCP_CONFIG` is unset, `load_mcp_servers()` returns `[]` and neither `TOOLS_SCHEMA` nor `TOOL_REGISTRY` is modified. Existing tests run without a config file and are unaffected.

## Run it

```bash
# Without MCP — 7 built-ins only
uv run main.py "list the src directory"

# With MCP filesystem server
AGENT_MCP_CONFIG=./mcp.json uv run main.py "list my open files using the filesystem server"

# GitHub MCP server (requires GITHUB_PERSONAL_ACCESS_TOKEN in mcp.json env)
AGENT_MCP_CONFIG=./mcp.json uv run main.py "list my open pull requests"
```

When an MCP tool is called, the output in the terminal is identical to a built-in call — the same `[✓ tool_name: N chars]` line from the renderer, the same `role: "tool"` message in history.

:::tip Architecture pattern
Merging MCP tools into the registry is [Plugin Architecture](../../architecture-patterns/plugin-architecture.md) over [Ports & Adapters](../../architecture-patterns/ports-and-adapters.md) — external capabilities behind the same tool interface as the built-ins.
:::

## Recap

`src/mcp_client.py` reads `AGENT_MCP_CONFIG`, opens `ClientSession` connections at startup, converts MCP tool descriptors to OpenAI-style schemas, and registers thin async wrappers in `TOOL_REGISTRY`. After `load_mcp_servers()` runs, the agent loop needs no changes — every MCP tool is callable by name exactly like a built-in, and its result flows back as a `role: "tool"` message in the standard message history.

The final layer in this phase gives you control over which model and provider the agent calls — down to a local Ollama instance or the Claude CLI itself.

→ [Layer 13.6 — Custom Models & Providers](./6-models-and-providers.md)
