---
sidebar_position: 1
title: Overview
description: What MCP is, why you'd use it with this agent, and how MCP tools merge into the same registry and loop as the 7 built-ins.
---

# Overview

The Model Context Protocol (MCP) is an open standard for exposing tools, resources, and prompts to LLM applications. An MCP server is a standalone process — or a remote HTTP endpoint — that declares what it can do via a JSON schema and executes calls on demand. This agent can act as an MCP client: connecting to one or more servers at startup, discovering their tools, and making those tools callable by the model in exactly the same way as the 7 built-ins.

:::note Status
v1 ships the 7 built-in tools (`read_file`, `write_file`, `edit_file`, `bash`, `grep`, `find_files`, `list_dir`) with no MCP client. MCP is the supported extension path for adding external tools without writing Python. The design described on these pages is planned; the integration point in `TOOL_REGISTRY` and `TOOLS_SCHEMA` is already well-defined.
:::

## Why MCP instead of writing more Python tools

Writing a built-in tool means touching `src/tools.py` — implementing the function, adding a schema entry, adding a registry entry — and testing it. That is the right approach for tools that are core to this project (see [Adding a Tool](../tools/adding-a-tool.md)).

MCP is right when:

- The tool is provided by an external ecosystem — a filesystem server, a GitHub API client, a Postgres query tool, a web browser controller.
- You want to share tools across agents or projects without copying implementation code.
- The tool is heavy enough to warrant its own process and lifecycle (e.g., a server that holds a long-lived database connection).

The MCP ecosystem already ships servers for common tasks:

| Server | What it adds |
|---|---|
| `@modelcontextprotocol/server-filesystem` | Read/write arbitrary filesystem paths, with access control |
| `@modelcontextprotocol/server-github` | Search repos, open issues, read PRs |
| `@modelcontextprotocol/server-postgres` | Query a Postgres database |
| `@modelcontextprotocol/server-puppeteer` | Control a headless browser |
| `mcp-server-sqlite` | Query SQLite databases |

Adding any of these takes a config entry, not a Python change.

## The core principle: MCP tools are indistinguishable from built-ins

This is the key architectural point. The agent loop in `src/agent.py` dispatches every tool call by name:

```python
# src/agent.py — _execute_one_tool
fn = TOOL_REGISTRY.get(name)
if fn is None:
    return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
result = await fn(**args)
```

It looks up a name in a dict and calls whatever is there. It does not know or care whether that function talks to a local Python library or forwards a call to a remote MCP server over stdio. The model likewise sees every tool purely through its schema entry in `TOOLS_SCHEMA` — a list of OpenAI-style dicts passed on every API call.

At startup, the MCP integration:

1. Reads the server config from `AGENT_MCP_CONFIG` (a path to a JSON file).
2. Opens an MCP `ClientSession` per server and calls `initialize()` and `list_tools()`.
3. For each discovered tool, converts its MCP JSON Schema into the project's OpenAI-style schema and **appends it to `TOOLS_SCHEMA`**.
4. Registers a thin async wrapper in **`TOOL_REGISTRY[name]`** that forwards calls to the server via `tools/call` and returns the result as a string.

After that, the loop runs unchanged.

## System diagram

```
MCP servers                Startup (once)               Agent loop (every turn)
─────────────              ──────────────               ───────────────────────

stdio server A  ──┐
                  ├─→  discover & adapt  ─→  TOOLS_SCHEMA (extended list)  ──→  model
stdio server B  ──┤        tools             TOOL_REGISTRY (name → fn)     ──→  dispatch
                  │
HTTP server C   ──┘
                                                                                  │
                                                         MCP wrapper  ←──── name lookup
                                                              │
                                                         tools/call
                                                              │
                                                         MCP server
```

The model receives the extended `TOOLS_SCHEMA` on every API call and can request any tool — built-in or MCP — without any loop-level change.

## Enabling MCP

Set `AGENT_MCP_CONFIG` to a path before running:

```bash
AGENT_MCP_CONFIG=./mcp.json python main.py "list my open GitHub PRs"
```

If `AGENT_MCP_CONFIG` is unset, no MCP client starts and only the 7 built-ins are available.

See [Settings Reference](../operations/settings.md) for how this fits alongside the other `AGENT_*` environment variables.

## Pages in this section

- [Connecting Servers](./connecting-servers.md) — the `mcp.json` config shape, the startup connection sequence, and session lifecycle.
- [MCP Tools in the Loop](./mcp-as-tools.md) — the adapter that converts an MCP tool into a schema entry and registry wrapper, name-collision handling, and security notes.

## Related pages

- [Tool Overview](../tools/overview.md) — the three-part contract (schema + function + registry) that MCP tools plug into.
- [Tool Schema Format](../tools/schema-format.md) — the OpenAI-style schema shape MCP tools are converted to.
- [Security Model](../operations/security.md) — MCP servers run external code; the same trust concerns apply as for the `bash` tool.
