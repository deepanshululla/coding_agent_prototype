"""MCP client: discover servers, adapt their tools, merge into the registry.

The Model Context Protocol lets the agent borrow tools from an external server
without writing an implementation for each. This module is the adapter:

1. Read ``AGENT_MCP_CONFIG`` (a JSON file, ``mcp.json`` shape) at startup.
2. Open a :class:`mcp.ClientSession` to each configured server.
3. Convert every MCP tool descriptor into the project's OpenAI-style schema
   dict and append it to :data:`tools.TOOLS_SCHEMA`.
4. Register a thin async wrapper in :data:`tools.TOOL_REGISTRY` that forwards
   the call to the server.

After :func:`load_mcp_servers` runs, the agent loop needs no changes — an MCP
tool is dispatched by ``TOOL_REGISTRY[name](**args)`` exactly like a built-in,
and its result flows back as a standard ``role: "tool"`` message.

The wrappers obey the cardinal tool rule (never raise — return an ``"Error:"``
string), and the real transport/session lifecycle is funnelled through
:func:`_connect_session` so the startup path can be unit-tested with a mock.
"""

from __future__ import annotations

import json
import os
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from tools import TOOL_REGISTRY, TOOLS_SCHEMA

# ── Schema conversion ─────────────────────────────────────────────────────────


def _mcp_tool_to_schema(tool, registered_name: str) -> dict:
    """Convert an MCP ``Tool`` descriptor to the project's OpenAI-style schema dict.

    ``registered_name`` may differ from ``tool.name`` when a collision forced a
    ``<server>__`` prefix — the model must see the name it should actually call.
    """
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
    """Return the registry key for an MCP tool.

    If the bare name is free, use it. If it already exists (a built-in such as
    ``read_file``, or a tool from an earlier server), prefix with
    ``<server_name>__`` so both remain callable and distinguishable.
    """
    if tool_name not in TOOL_REGISTRY:
        return tool_name
    return f"{server_name}__{tool_name}"


# ── Dispatch wrapper ──────────────────────────────────────────────────────────


def _make_mcp_wrapper(session, tool_name: str):
    """Return an async callable that forwards a tool call to the MCP ``session``.

    ``tool_name`` is the server's *original* name (not the possibly-prefixed
    registry key). The wrapper flattens the response content blocks to text and,
    per the tool contract, converts any failure into an ``"Error:"`` string
    rather than raising into the agent loop.
    """

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
                parts.append(f"[{getattr(block, 'type', 'non-text')} content omitted]")

        joined = "\n".join(parts)
        if getattr(result, "isError", False):
            return "Error: " + joined
        return joined or "(empty result)"

    return wrapper


# ── Registration ──────────────────────────────────────────────────────────────


def _register_mcp_tools(session, server_name: str, tools) -> None:
    """Append schemas and register wrappers for all tools from one MCP server."""
    for tool in tools:
        registered_name = _resolve_name(tool.name, server_name)
        TOOLS_SCHEMA.append(_mcp_tool_to_schema(tool, registered_name))
        TOOL_REGISTRY[registered_name] = _make_mcp_wrapper(session, tool.name)


# ── Connection ────────────────────────────────────────────────────────────────


class _ManagedSession:
    """A :class:`ClientSession` paired with the :class:`AsyncExitStack` that owns
    its transport, exposing a single ``aclose()`` for the caller's try/finally.

    The real ``mcp`` API hands back async context managers for both the transport
    (stdio/http) and the session; tearing them down in the right order is what
    the exit stack guarantees. Delegating attribute access keeps this object a
    drop-in ``ClientSession`` for everything else (``call_tool``, ``list_tools``).
    """

    def __init__(self, session: ClientSession, stack: AsyncExitStack):
        self._session = session
        self._stack = stack

    def __getattr__(self, item):
        return getattr(self._session, item)

    async def aclose(self) -> None:
        await self._stack.aclose()


async def _connect_session(server_cfg: dict):
    """Open and initialize a session for one server config.

    Picks the transport from the config shape: ``url`` → streamable-http,
    otherwise ``command`` → stdio. Returns a closeable session-like object.

    This is the single seam the unit tests replace, so the startup logic in
    :func:`load_mcp_servers` can run without a live server.
    """
    stack = AsyncExitStack()
    if "url" in server_cfg:
        read, write, *_ = await stack.enter_async_context(streamablehttp_client(server_cfg["url"]))
    else:
        params = StdioServerParameters(
            command=server_cfg["command"],
            args=server_cfg.get("args", []),
            env={**os.environ, **server_cfg.get("env", {})},
        )
        read, write = await stack.enter_async_context(stdio_client(params))

    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    return _ManagedSession(session, stack)


# ── Startup ───────────────────────────────────────────────────────────────────


async def load_mcp_servers() -> list:
    """Read ``AGENT_MCP_CONFIG``, connect to each server, and register their tools.

    Returns the open sessions so the caller can close them on exit. When
    ``AGENT_MCP_CONFIG`` is unset this is a no-op: it returns ``[]`` and leaves
    ``TOOLS_SCHEMA`` / ``TOOL_REGISTRY`` exactly as the built-ins left them.

    Must run *before* the first model call so ``TOOLS_SCHEMA`` is fully populated.
    """
    config_path = os.environ.get("AGENT_MCP_CONFIG")
    if not config_path:
        return []

    with open(config_path) as f:
        config = json.load(f)

    sessions: list = []
    for server_name, server_cfg in config.get("mcpServers", {}).items():
        try:
            session = await _connect_session(server_cfg)
        except Exception as e:
            raise RuntimeError(f"Failed to connect to MCP server '{server_name}': {e}") from e

        tools_result = await session.list_tools()
        _register_mcp_tools(session, server_name, tools_result.tools)
        sessions.append(session)

    return sessions
