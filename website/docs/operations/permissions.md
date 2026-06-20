---
sidebar_position: 4
title: Permissions & Gating
description: How to add a beforeToolCall-style permission hook to _execute_one_tool that lets you approve or deny dangerous tool calls before they execute.
---

# Permissions & Gating

By default the agent executes every tool call the LLM requests without asking for confirmation. For read-only tasks this is fine. For tasks that involve `bash`, `write_file`, or `edit_file`, you may want a human to confirm before anything is executed.

:::note
Permission gating is a planned extension. `PLAN.md` explicitly skips `beforeToolCall`/`afterToolCall` hooks in v1 ("Add if you want permission prompts"). This page describes the design so you can add it yourself once the core loop is working. The hook point (`_execute_one_tool` in `src/agent.py`) is well-defined even before the feature is built.
:::

## The hook point

All tool execution flows through a single function in `src/agent.py`:

```python
async def _execute_one_tool(tool_call: dict) -> ToolResult:
    name = tool_call["name"]
    args = tool_call["input"]
    print(f"  [executing {name} {args}]")
    try:
        fn = TOOL_REGISTRY.get(name)
        if fn is None:
            return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
        result = await fn(**args)
        return ToolResult(tool_call["id"], name, result)
    except Exception as e:
        return ToolResult(tool_call["id"], name, str(e), is_error=True)
```

A permission gate lives between the `name`/`args` extraction and the `fn(**args)` call. This is the `beforeToolCall` pattern — inspect what is about to run, then approve, deny, or transform it.

## Adding a permission gate

```python
# src/agent.py

# Tools that require explicit approval before execution
DANGEROUS_TOOLS = {"bash", "write_file", "edit_file"}

# Tools that are always auto-approved (read-only)
SAFE_TOOLS = {"read_file", "grep", "find_files", "list_dir"}

async def _before_tool_call(name: str, args: dict) -> bool:
    """
    Return True to allow execution, False to deny.
    Called once per tool call, before the tool function runs.
    """
    if name in SAFE_TOOLS:
        return True  # auto-approve read-only tools

    if name in DANGEROUS_TOOLS:
        # Format the call for human review
        print(f"\n[PERMISSION REQUEST] Tool: {name}")
        for key, value in args.items():
            preview = str(value)[:200] + ("..." if len(str(value)) > 200 else "")
            print(f"  {key}: {preview}")
        response = input("Allow? [y/N] ").strip().lower()
        return response == "y"

    # Unknown tools default to deny
    print(f"[PERMISSION DENIED] Unknown tool '{name}' not in any list.")
    return False

async def _execute_one_tool(tool_call: dict) -> ToolResult:
    name = tool_call["name"]
    args = tool_call["input"]

    # ── Permission gate ───────────────────────────────────────────────────
    allowed = await _before_tool_call(name, args)
    if not allowed:
        return ToolResult(
            tool_call["id"],
            name,
            f"Tool call '{name}' was denied by the user.",
            is_error=True,
        )
    # ─────────────────────────────────────────────────────────────────────

    print(f"  [executing {name} {args}]")
    try:
        fn = TOOL_REGISTRY.get(name)
        if fn is None:
            return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
        result = await fn(**args)
        print(f"  [✓ {name}: {len(result)} chars]")
        return ToolResult(tool_call["id"], name, result)
    except Exception as e:
        return ToolResult(tool_call["id"], name, str(e), is_error=True)
```

When the agent requests a `bash` call, the user sees:

```
[PERMISSION REQUEST] Tool: bash
  command: pytest tests/ -x
Allow? [y/N]
```

Type `y` to proceed, anything else to deny. A denied call returns an error string to the LLM, which can then try a different approach.

## Allowlist and denylist patterns

For finer control, match on tool arguments rather than just tool name.

:::tip Command allowlist
For the `bash` tool specifically, a default-deny **command allowlist** is the strongest
control — and the shell-parsing pitfalls below (chaining, substitution, redirects) are
covered in depth on its own page. See **[Command Allowlist](./command-allowlist.md)**.
:::

### Pattern matching on bash commands

```python
import re

# Always deny these patterns regardless of anything else
BASH_DENYLIST = [
    r"rm\s+-rf\s+/",        # rm -rf /
    r"curl\s+.*\|\s*sh",    # curl | sh
    r">\s*/etc/",           # write to /etc
    r"dd\s+if=",            # dd if=... (disk writes)
]

# Auto-approve these safe bash patterns
BASH_ALLOWLIST = [
    r"^git\s+(status|log|diff|show)",   # read-only git
    r"^cat\s+",                          # cat (read)
    r"^ls(\s|$)",                        # ls
    r"^pytest\s+",                       # run tests
    r"^python\s+.*\.py$",               # run a script
]

def check_bash_command(command: str) -> str:
    """Returns 'allow', 'deny', or 'prompt'."""
    for pattern in BASH_DENYLIST:
        if re.search(pattern, command):
            return "deny"
    for pattern in BASH_ALLOWLIST:
        if re.search(pattern, command):
            return "allow"
    return "prompt"
```

Then in `_before_tool_call`:

```python
if name == "bash":
    decision = check_bash_command(args.get("command", ""))
    if decision == "deny":
        print(f"[AUTO-DENIED] bash: {args['command']}")
        return False
    if decision == "allow":
        return True
    # decision == "prompt" — fall through to human review
```

### Path restrictions for file tools

```python
import pathlib

ALLOWED_WRITE_ROOT = pathlib.Path("/workspace")   # or os.getcwd()

def check_file_path(path: str) -> bool:
    """Return True if the path is under the allowed write root."""
    try:
        resolved = pathlib.Path(path).resolve()
        return resolved.is_relative_to(ALLOWED_WRITE_ROOT)
    except ValueError:
        return False
```

Apply in `_before_tool_call` for `write_file` and `edit_file`:

```python
if name in {"write_file", "edit_file"}:
    path = args.get("path", "")
    if not check_file_path(path):
        print(f"[AUTO-DENIED] {name}: path {path!r} is outside {ALLOWED_WRITE_ROOT}")
        return False
```

## Auto-approving read-only tools

The 7 tools split cleanly into read-only and write/execute:

| Tool | Category | Default gate |
|---|---|---|
| `read_file` | Read-only | Auto-approve |
| `grep` | Read-only | Auto-approve |
| `find_files` | Read-only | Auto-approve |
| `list_dir` | Read-only | Auto-approve |
| `bash` | Execute | Prompt (or pattern-match) |
| `write_file` | Write | Prompt (or path-check) |
| `edit_file` | Write | Prompt (or path-check) |

Auto-approving read-only tools keeps the agent flowing without interruption for exploration phases, while surfacing writes and shell commands for review.

## Interaction with parallel execution

Tool calls execute in parallel via `asyncio.gather`. When multiple tool calls are requested in the same turn (e.g., `read_file` + `bash` in parallel), each goes through `_execute_one_tool` concurrently. If `_before_tool_call` uses `input()` to prompt the user, concurrent prompts will interleave on the terminal — which is confusing.

Two options:

1. **Serialize dangerous prompts.** Use an `asyncio.Lock` around the user-prompt path in `_before_tool_call`. Read-only auto-approvals bypass the lock and stay concurrent.

2. **Batch and prompt once.** Collect all pending tool calls, show them together, and ask once before dispatching any. This requires a small restructure of `_execute_tools_parallel` to allow a pre-approval phase.

For a v1 gate, option 1 is simpler.

```python
_prompt_lock = asyncio.Lock()

async def _before_tool_call(name: str, args: dict) -> bool:
    if name in SAFE_TOOLS:
        return True
    async with _prompt_lock:
        # Only one prompt at a time
        print(f"\n[PERMISSION REQUEST] Tool: {name}")
        ...
        response = input("Allow? [y/N] ").strip().lower()
        return response == "y"
```

## Related pages

- [Security Model](./security.md) — the threat model that motivates permission gating
- [Extensions & Hooks](../customization/extensions-and-hooks.md) — other places to inject behavior into the agent loop
