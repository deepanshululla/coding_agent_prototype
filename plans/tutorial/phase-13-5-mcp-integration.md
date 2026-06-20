Status: not started

# Phase 13.5 — MCP Integration

## Goal

Create `src/mcp_client.py` to read `AGENT_MCP_CONFIG`, connect to MCP servers at startup, and merge their tool descriptors into `TOOLS_SCHEMA` / `TOOL_REGISTRY` so MCP tools are callable by the agent loop identically to the 7 built-ins.

## Files changed

| File | Change |
|---|---|
| `src/mcp_client.py` | New module — `_mcp_tool_to_schema`, `_resolve_name`, `_make_mcp_wrapper`, `_register_mcp_tools`, `load_mcp_servers` |
| `main.py` | Call `load_mcp_servers()` before `build_system_prompt`; wrap `run_agent` in try/finally to `aclose()` sessions |
| `mcp.json` | New example config with `filesystem` stdio server for local testing |
| `tests/test_mcp_client.py` | New tests — schema conversion; name-collision prefixing; `load_mcp_servers()` returns `[]` when `AGENT_MCP_CONFIG` unset; mock MCP session registers tool in registry and schema |

## Order of operations

1. Write a failing test: `_mcp_tool_to_schema(mock_tool, "list_directory")` returns a dict with `"type": "function"` and correct `name`/`description`/`parameters`. Confirm `ImportError`.
2. Create `src/mcp_client.py` with `_mcp_tool_to_schema` only. Run test — green.
3. Write test for `_resolve_name`: no collision returns original name; existing name in registry returns `"server__name"`. Add `_resolve_name` and run.
4. Write test that `load_mcp_servers()` with `AGENT_MCP_CONFIG` unset returns `[]` and leaves `TOOLS_SCHEMA`/`TOOL_REGISTRY` unchanged. Add `load_mcp_servers` stub and run.
5. Write an integration test using a mock `ClientSession`: `_register_mcp_tools` appends to `TOOLS_SCHEMA` and adds a callable to `TOOL_REGISTRY`; calling that callable returns the session's response text. Add `_make_mcp_wrapper` and `_register_mcp_tools`, run test.
6. Extend `load_mcp_servers` to handle both `url` (streamable-http) and `command` (stdio) server configs. Write a test with a mock stdio server.
7. Update `main.py`: await `load_mcp_servers()` before `build_system_prompt`; wrap in try/finally with `session.aclose()`. Run `uv run pytest -q`.
8. Create `mcp.json` with the filesystem example. Smoke-test: `AGENT_MCP_CONFIG=./mcp.json uv run main.py "read README.md using the filesystem MCP server"`.

## Verification

- [ ] Tests added: `tests/test_mcp_client.py`
- [ ] Full suite: `uv run pytest -q` — when `AGENT_MCP_CONFIG` is unset, `load_mcp_servers()` returns `[]` and no existing test is affected
- [ ] No MCP: `uv run main.py "list the src directory"` — 7 built-ins only, no change in behavior
- [ ] With MCP: `AGENT_MCP_CONFIG=./mcp.json uv run main.py "list my open files using the filesystem server"` — MCP tool callable, result formatted identically to built-in
- [ ] Name collision: if MCP server exports `read_file`, it is registered as `filesystem__read_file` in `TOOL_REGISTRY`

### Acceptance (BDD)

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

## Notes / open questions

- `load_mcp_servers()` must be called before `build_system_prompt` (not because the prompt uses tool names directly, but so `TOOLS_SCHEMA` is fully populated before the first API call).
- The `mcp` package must be added to `pyproject.toml` dependencies.
- MCP servers run external code and can access files beyond the working directory — treat with the same posture as the `bash` tool; run in a container for untrusted servers.
- Session `aclose()` must run even if `run_agent` raises — the try/finally in `main.py` handles this.
- `_make_mcp_wrapper` catches all exceptions and returns an error string, consistent with the "never raise from tools" contract.

---

**Tutorial build step 25 of 32** · ← [Phase 13.4 — Agent Skills (Install & Read)](./phase-13-4-agent-skills.md) · [Phase 13.6 — Custom Models & Providers](./phase-13-6-models-and-providers.md) →
