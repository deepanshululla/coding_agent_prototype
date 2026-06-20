"""Tests for the MCP client adapter (Layer 13.5).

These exercise the pure adapter logic — schema conversion, name-collision
prefixing, the dispatch wrapper — plus the startup contract that
``load_mcp_servers()`` is a no-op when ``AGENT_MCP_CONFIG`` is unset.

The MCP session itself is mocked: spinning up a live stdio/http server needs
an external process, so the unit tests drive a fake ``ClientSession`` that
records the calls the wrapper forwards. The live path is smoke-tested manually
(see the plan's Verification section).
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import mcp_client
import tools


@pytest.fixture
def clean_registry():
    """Snapshot TOOLS_SCHEMA / TOOL_REGISTRY and restore them after the test.

    The adapter mutates module-level globals; without this fixture a test that
    registers an MCP tool would leak it into every later test.
    """
    schema_before = list(tools.TOOLS_SCHEMA)
    registry_before = dict(tools.TOOL_REGISTRY)
    yield
    tools.TOOLS_SCHEMA[:] = schema_before
    tools.TOOL_REGISTRY.clear()
    tools.TOOL_REGISTRY.update(registry_before)


def _fake_tool(name, description="desc", schema=None):
    return SimpleNamespace(
        name=name,
        description=description,
        inputSchema=schema or {"type": "object", "properties": {}},
    )


# ── _mcp_tool_to_schema ───────────────────────────────────────────────────────


def test_mcp_tool_to_schema_shape():
    tool = _fake_tool(
        "list_directory",
        description="List a directory on the server",
        schema={"type": "object", "properties": {"path": {"type": "string"}}},
    )
    result = mcp_client._mcp_tool_to_schema(tool, "list_directory")
    assert result["type"] == "function"
    assert result["function"]["name"] == "list_directory"
    assert result["function"]["description"] == "List a directory on the server"
    assert result["function"]["parameters"] == {
        "type": "object",
        "properties": {"path": {"type": "string"}},
    }


def test_mcp_tool_to_schema_uses_registered_name():
    tool = _fake_tool("read_file")
    result = mcp_client._mcp_tool_to_schema(tool, "filesystem__read_file")
    assert result["function"]["name"] == "filesystem__read_file"


def test_mcp_tool_to_schema_handles_missing_description():
    tool = _fake_tool("x", description=None)
    result = mcp_client._mcp_tool_to_schema(tool, "x")
    assert result["function"]["description"] == ""


# ── _resolve_name ─────────────────────────────────────────────────────────────


def test_resolve_name_no_collision(clean_registry):
    assert mcp_client._resolve_name("list_directory", "filesystem") == "list_directory"


def test_resolve_name_collision_prefixes_server(clean_registry):
    # read_file is a built-in already in the registry.
    assert mcp_client._resolve_name("read_file", "filesystem") == "filesystem__read_file"


# ── load_mcp_servers: unset config ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_mcp_servers_no_config(monkeypatch, clean_registry):
    monkeypatch.delenv("AGENT_MCP_CONFIG", raising=False)
    schema_len = len(tools.TOOLS_SCHEMA)
    registry_keys = set(tools.TOOL_REGISTRY)

    sessions = await mcp_client.load_mcp_servers()

    assert sessions == []
    assert len(tools.TOOLS_SCHEMA) == schema_len
    assert set(tools.TOOL_REGISTRY) == registry_keys


# ── _make_mcp_wrapper + _register_mcp_tools ───────────────────────────────────


class _FakeBlock:
    def __init__(self, text):
        self.text = text
        self.type = "text"


class _FakeResult:
    def __init__(self, content, is_error=False):
        self.content = content
        self.isError = is_error


class _FakeSession:
    """Records call_tool invocations and returns a canned result."""

    def __init__(self, result):
        self._result = result
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self._result


@pytest.mark.asyncio
async def test_wrapper_returns_response_text():
    session = _FakeSession(_FakeResult([_FakeBlock("entry-a\nentry-b")]))
    wrapper = mcp_client._make_mcp_wrapper(session, "list_directory")
    out = await wrapper(path=".")
    assert out == "entry-a\nentry-b"
    assert session.calls == [("list_directory", {"path": "."})]


@pytest.mark.asyncio
async def test_wrapper_formats_error_result():
    session = _FakeSession(_FakeResult([_FakeBlock("boom")], is_error=True))
    wrapper = mcp_client._make_mcp_wrapper(session, "list_directory")
    out = await wrapper()
    assert out.startswith("Error:")
    assert "boom" in out


@pytest.mark.asyncio
async def test_wrapper_never_raises_on_exception():
    class Boom:
        async def call_tool(self, name, arguments):
            raise RuntimeError("connection dropped")

    wrapper = mcp_client._make_mcp_wrapper(Boom(), "list_directory")
    out = await wrapper()
    assert out.startswith("Error calling MCP tool 'list_directory'")
    assert "connection dropped" in out


@pytest.mark.asyncio
async def test_register_mcp_tools_adds_schema_and_callable(clean_registry):
    session = _FakeSession(_FakeResult([_FakeBlock("ok")]))
    tool = _fake_tool("list_directory", description="List a dir")

    mcp_client._register_mcp_tools(session, "filesystem", [tool])

    assert "list_directory" in tools.TOOL_REGISTRY
    names = [s["function"]["name"] for s in tools.TOOLS_SCHEMA]
    assert "list_directory" in names
    descs = {s["function"]["name"]: s["function"]["description"] for s in tools.TOOLS_SCHEMA}
    assert descs["list_directory"] == "List a dir"

    # The registered callable dispatches to the session.
    out = await tools.TOOL_REGISTRY["list_directory"]()
    assert out == "ok"


@pytest.mark.asyncio
async def test_register_mcp_tools_prefixes_on_collision(clean_registry):
    session = _FakeSession(_FakeResult([_FakeBlock("ok")]))
    tool = _fake_tool("read_file")  # collides with built-in

    mcp_client._register_mcp_tools(session, "filesystem", [tool])

    assert "filesystem__read_file" in tools.TOOL_REGISTRY
    # Built-in read_file untouched.
    assert tools.TOOL_REGISTRY["read_file"] is tools.read_file
    # The wrapper forwards the server's *original* tool name, not the prefixed one.
    await tools.TOOL_REGISTRY["filesystem__read_file"]()
    assert session.calls[0][0] == "read_file"


# ── load_mcp_servers: full startup with mocked transport/session ──────────────


@pytest.mark.asyncio
async def test_load_mcp_servers_registers_and_returns_session(
    monkeypatch, tmp_path, clean_registry
):
    config = tmp_path / "mcp.json"
    config.write_text('{"mcpServers": {"filesystem": {"command": "noop", "args": [], "env": {}}}}')
    monkeypatch.setenv("AGENT_MCP_CONFIG", str(config))

    closed = {"value": False}

    class FakeSession:
        async def initialize(self):
            return None

        async def list_tools(self):
            return SimpleNamespace(tools=[_fake_tool("list_directory")])

        async def call_tool(self, name, arguments):
            return _FakeResult([_FakeBlock("ok")])

        async def aclose(self):
            closed["value"] = True

    # Patch the connection seam so no real subprocess/network is touched.
    async def fake_connect(server_cfg):
        return FakeSession()

    monkeypatch.setattr(mcp_client, "_connect_session", fake_connect)

    sessions = await mcp_client.load_mcp_servers()

    assert len(sessions) == 1
    assert "list_directory" in tools.TOOL_REGISTRY
    names = [s["function"]["name"] for s in tools.TOOLS_SCHEMA]
    assert "list_directory" in names

    # Sessions are closeable for the main.py try/finally.
    await sessions[0].aclose()
    assert closed["value"] is True
