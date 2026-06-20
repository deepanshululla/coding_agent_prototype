---
sidebar_position: 2
title: Plugin Architecture
description: Turn every tool into a self-describing plugin so you can add GitHub, Jira, Slack, or Kubernetes capabilities without touching the agent core.
---

# Plugin Architecture

The agent's tool set is a first-class extension point. The plugin architecture formalizes that boundary so any new capability — `repo_search`, `github`, `jira`, `slack`, `kubernetes` — drops in without a single edit to `agent.py`.

## The problem

A coding agent needs tools. At first you write seven of them directly in `tools.py` and hardcode them into `TOOLS_SCHEMA` and `TOOL_REGISTRY`. That works fine for seven. It stops working when you want to add a twelfth, or when you want to ship a version of the agent that has the `github` tool enabled only in CI, or when a teammate wants to add a `jira` tool without understanding the full agent loop.

The failure mode isn't a crash — it's a merge conflict in `tools.py` and a ritual of "edit three places in two files" every time anyone adds a capability.

## The pattern

A plugin is a self-describing unit:

- **metadata** the agent core can read without executing anything (`name`, `description`, `input_schema`)
- **policy metadata** the host can check before execution (`permission_level`)
- **an `execute()` callable** that actually does the work

The core never imports individual tools by name. It discovers them through a registry and dispatches through a uniform interface. Adding a plugin is registering it; removing is unregistering it.

```
  tools/
  ├── repo_search/     ← one plugin per directory
  │   ├── __init__.py
  │   └── plugin.py    ← exposes Plugin instance
  ├── file_editor/
  ├── shell_runner/
  ├── test_runner/
  ├── github/
  ├── jira/
  ├── docs_search/
  └── registry.py      ← discovers & assembles TOOL_REGISTRY + TOOLS_SCHEMA
```

The agent loop never changes. It still reads `TOOL_REGISTRY` and `TOOLS_SCHEMA` — the registry just builds those from whatever plugins are installed.

## In this project

`src/tools.py` already **is** a plugin system, just an informal one. Each of the seven tools is three things bound together: an `async def` implementation, an OpenAI-format schema dict in `TOOLS_SCHEMA`, and an entry in `TOOL_REGISTRY`. Formalizing means extracting that bundle into a `Plugin` dataclass and writing a discovery step.

:::note Planned pattern, not yet shipped
The shipped `src/tools.py` uses the flat dictionary approach. The formalization below is the recommended next step when you start adding tools beyond the core seven.
:::

**Step 1 — Define a `Plugin` protocol**

```python
# src/plugin.py
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable, Coroutine
from typing import Any, Literal

PermissionLevel = Literal["read", "write", "network", "shell"]


@dataclass
class Plugin:
    """A self-describing, executable unit of agent capability."""

    name: str
    description: str
    input_schema: dict          # JSON Schema for the arguments
    execute: Callable[..., Coroutine[Any, Any, str]]  # async def; never raises
    permission_level: PermissionLevel = "read"

    def to_tool_schema(self) -> dict:
        """Emit the OpenAI-style schema entry the model expects."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }
```

**Step 2 — Wrap each existing tool as a `Plugin`**

```python
# tools/file_editor/plugin.py
from src.plugin import Plugin
from src.tools import read_file, write_file, edit_file

read_file_plugin = Plugin(
    name="read_file",
    description="Read the contents of a file. Use offset/limit for large files.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer", "default": 0},
            "limit": {"type": "integer", "default": 2000},
        },
        "required": ["path"],
    },
    execute=read_file,
    permission_level="read",
)
```

**Step 3 — Build the registry from installed plugins**

```python
# src/registry.py
from src.plugin import Plugin

# Replace this list with dynamic discovery (importlib, entry points, env flag)
_PLUGINS: list[Plugin] = []


def register(plugin: Plugin) -> None:
    _PLUGINS.append(plugin)


def build_tool_registry() -> dict[str, Plugin]:
    return {p.name: p for p in _PLUGINS}


def build_tools_schema() -> list[dict]:
    return [p.to_tool_schema() for p in _PLUGINS]
```

**Step 4 — Update `_execute_one_tool` to dispatch through the registry**

The change in `agent.py` is minimal. Currently:

```python
# src/agent.py  (current)
fn = TOOL_REGISTRY.get(name)
if fn is None:
    return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
result = await fn(**args)
```

With plugins, `TOOL_REGISTRY` maps to `Plugin` objects instead of raw callables, but `_execute_one_tool` only needs one line changed:

```python
# src/agent.py  (with plugin registry)
plugin = TOOL_REGISTRY.get(name)
if plugin is None:
    return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
result = await plugin.execute(**args)
```

The `permission_level` field on each `Plugin` is available here before the call — hand it to the [policy engine](./policy-engine.md) to decide whether execution is allowed.

**Adding `github` without touching the core**

```python
# tools/github/plugin.py
import httpx
from src.plugin import Plugin


async def create_pull_request(repo: str, title: str, body: str, head: str, base: str) -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.github.com/repos/{repo}/pulls",
                headers={"Authorization": f"Bearer {token}"},
                json={"title": title, "body": body, "head": head, "base": base},
            )
        resp.raise_for_status()
        data = resp.json()
        return f"Created PR #{data['number']}: {data['html_url']}"
    except Exception as e:
        return f"Error: {e}"   # never raise — return the error string


github_plugin = Plugin(
    name="create_pull_request",
    description="Open a GitHub pull request.",
    input_schema={
        "type": "object",
        "properties": {
            "repo": {"type": "string", "description": "owner/name"},
            "title": {"type": "string"},
            "body": {"type": "string"},
            "head": {"type": "string"},
            "base": {"type": "string", "default": "main"},
        },
        "required": ["repo", "title", "body", "head"],
    },
    execute=create_pull_request,
    permission_level="network",
)
```

Register it at startup and the agent can call `create_pull_request` — zero changes to the loop.

**Discovery via entry points (optional)**

For a fully decoupled plugin ecosystem, use Python's `importlib.metadata` entry points so external packages can contribute plugins:

```python
# src/registry.py  (discovery variant)
from importlib.metadata import entry_points

def discover_plugins() -> list[Plugin]:
    found = []
    for ep in entry_points(group="coding_agent.tools"):
        plugin = ep.load()   # each entry point returns a Plugin instance
        found.append(plugin)
    return found
```

A third-party `coding-agent-jira` package declares `coding_agent.tools = jira_plugin` in its `pyproject.toml` and the agent picks it up on next startup.

## Trade-offs

| | Plugin architecture | Flat `tools.py` |
|---|---|---|
| **Adding a tool** | Drop a file, register one object | Edit `TOOLS_SCHEMA` + `TOOL_REGISTRY` in the same file |
| **Disabling a tool** | Skip registration | Delete or comment out entries in two places |
| **Permission checking** | `plugin.permission_level` is available at dispatch time | Requires separate lookup or inlining in the tool itself |
| **Testability** | Swap a fake plugin in tests with no patching | Must patch module-level dicts |
| **Overhead** | One indirection layer | Zero indirection |
| **Right time to adopt** | When you reach ~10 tools or need conditional loading | While you have ≤7 tools from one team |

Adopt when: you're adding tools from multiple sources (internal, external packages, user-defined), you need to enable/disable tools per environment, or you want the policy engine to gate on `permission_level`.

Skip for now if: you have a stable set of core tools and no external contributors. The flat approach in `tools.py` is cleaner at small scale.

## Related

- [Tools overview](../tools/overview.md)
- [Adding a tool](../tools/adding-a-tool.md)
- [MCP overview](../mcp/overview.md)
- [Command Pattern](./command-pattern.md)
- [Policy Engine](./policy-engine.md)
