---
sidebar_position: 3
title: "Layer 12.3 — Permissions & Modes"
description: Add a PolicyEngine and AGENT_PERMISSION_MODE switch so the same agent binary can run read-only, prompt before dangerous actions, or execute autonomously within the allowlist.
---

# Layer 12.3 — Permissions & Modes

:::note Starting point
The agent from Layer 12.2: a command allowlist gate in `_execute_one_tool` refuses unlisted programs. Every other tool call — including `write_file` and `edit_file` — still executes without confirmation. There is no way to lock the agent to read-only or to require human approval before file writes.
:::

The allowlist controls which *shell commands* may run. It says nothing about `write_file`, `edit_file`, or what happens when the model requests `bash` with a command that is allowlisted but dangerous in context. The right level of autonomy also depends on *when* you run the agent: free exploration of an unfamiliar codebase calls for read-only mode; interactive development calls for per-action approval; CI calls for fully automated execution within the allowlist.

This layer introduces two things that work together:

1. **A `PolicyEngine`** — a composable, deterministic gate that evaluates every tool call before dispatch and returns `allow`, `ask`, or `deny`.
2. **`AGENT_PERMISSION_MODE`** — a single environment variable (`read-only` / `ask` / `auto`) that selects the engine's rule set and default outcome.

The design is detailed in [Permissions & Gating](../../operations/permissions.md), [Policy Engine / Guards](../../architecture-patterns/policy-engine.md), and [Permission Modes](../../architecture-patterns/permission-modes.md).

## What you'll learn

- Why a code-level gate is more reliable than a system-prompt instruction ("never run rm -rf").
- How to compose `ReadOnlyRule`, `CommandAllowlistRule`, and `PathRestrictionRule` into a single `PolicyEngine`.
- How `AGENT_PERMISSION_MODE` selects the right posture per invocation without code changes.
- How `ask` mode serializes approval prompts so parallel tool calls don't interleave on the terminal.

## Build it

### Step 1 — Create `src/policy.py`

```python
# src/policy.py

"""Policy engine: a composable gate that answers 'can this tool call run?'
before _execute_one_tool dispatches to the tool function.

Usage:
    _policy = PolicyEngine.from_env()   # call once at module level

    decision = _policy.check(name, args)
    if decision.outcome == "deny":
        return ToolResult(..., is_error=True)
    if decision.outcome == "ask":
        approved = await _prompt_user(name, args)
        if not approved:
            return ToolResult(..., is_error=True)
    # outcome == "allow" — dispatch
"""

from __future__ import annotations

import asyncio
import os
import pathlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal


# ── Decision ─────────────────────────────────────────────────────────────────

@dataclass
class Decision:
    outcome: Literal["allow", "deny", "ask"]
    reason: str = ""


# ── Rules ────────────────────────────────────────────────────────────────────

class Rule(ABC):
    @abstractmethod
    def evaluate(self, tool_name: str, args: dict) -> Decision | None:
        """Return a Decision to short-circuit, or None to pass to the next rule."""
        ...


class ReadOnlyRule(Rule):
    """Deny all write and execute tools unconditionally."""
    WRITE_EXECUTE = {"bash", "write_file", "edit_file"}

    def evaluate(self, tool_name: str, args: dict) -> Decision | None:
        if tool_name in self.WRITE_EXECUTE:
            return Decision(
                "deny",
                f"'{tool_name}' is a write/execute tool; read-only mode is active",
            )
        return None


class CommandAllowlistRule(Rule):
    """Apply the command allowlist to bash calls (Layer 12.2)."""

    def evaluate(self, tool_name: str, args: dict) -> Decision | None:
        if tool_name != "bash":
            return None
        from allowlist import check_command
        verdict = check_command(args.get("command", ""))
        if not verdict.allowed:
            return Decision("deny", verdict.reason)
        return Decision("allow")   # allowlisted — no need to ask


class PathRestrictionRule(Rule):
    """Deny file writes outside the allowed root (default: cwd)."""

    def __init__(self, allowed_root: str | None = None):
        self.root = pathlib.Path(allowed_root or os.getcwd()).resolve()

    def evaluate(self, tool_name: str, args: dict) -> Decision | None:
        if tool_name not in {"write_file", "edit_file"}:
            return None
        try:
            resolved = pathlib.Path(args.get("path", "")).resolve()
            if not resolved.is_relative_to(self.root):
                return Decision(
                    "deny",
                    f"path {resolved} is outside allowed root {self.root}",
                )
        except ValueError:
            return Decision("deny", "could not resolve path")
        return None   # path is safe; let other rules decide


# ── Engine ───────────────────────────────────────────────────────────────────

class PolicyEngine:
    """Evaluate a tool call against an ordered list of rules.

    The first rule that returns a non-None Decision wins.
    If no rule matches, the engine's default outcome applies.
    """

    def __init__(
        self,
        rules: list[Rule],
        default: Literal["allow", "deny", "ask"] = "ask",
    ):
        self.rules = rules
        self.default = default

    @classmethod
    def from_env(cls) -> PolicyEngine:
        """Build an engine from AGENT_PERMISSION_MODE (default: 'ask')."""
        mode = os.environ.get("AGENT_PERMISSION_MODE", "ask")

        if mode == "read-only":
            return cls(
                rules=[ReadOnlyRule()],
                default="deny",
            )

        if mode == "auto":
            return cls(
                rules=[
                    CommandAllowlistRule(),
                    PathRestrictionRule(),
                ],
                default="deny",   # auto still denies unknown/unlisted calls
            )

        # mode == "ask" (default)
        return cls(
            rules=[
                CommandAllowlistRule(),   # allowlisted bash calls run without prompting
                PathRestrictionRule(),    # out-of-root writes are denied without prompting
            ],
            default="ask",   # everything else goes to the user
        )

    def check(self, tool_name: str, args: dict) -> Decision:
        for rule in self.rules:
            decision = rule.evaluate(tool_name, args)
            if decision is not None:
                return decision
        return Decision(outcome=self.default, reason="no matching rule; default applied")
```

### Step 2 — Wire the engine into `_execute_one_tool`

Replace the Layer 12.2 allowlist gate in `src/agent.py` with the policy engine. The allowlist check is now encapsulated inside `CommandAllowlistRule`; `_execute_one_tool` no longer calls `check_command` directly.

Add the import and the module-level singleton at the top of `src/agent.py`:

```python
import asyncio
from policy import PolicyEngine, Decision

_policy = PolicyEngine.from_env()   # reads AGENT_PERMISSION_MODE once at startup
_prompt_lock = asyncio.Lock()       # serialise stdin prompts in ask mode
```

Then replace the previous gate with the engine call:

```python
async def _execute_one_tool(tool_call: dict) -> ToolResult:
    name = tool_call["name"]
    args = tool_call["input"]

    # ── Policy gate ───────────────────────────────────────────────────────
    decision = _policy.check(name, args)

    if decision.outcome == "deny":
        return ToolResult(
            tool_call["id"], name,
            f"Error: tool call denied — {decision.reason}",
            is_error=True,
        )

    if decision.outcome == "ask":
        approved = await _prompt_user(name, args)
        if not approved:
            return ToolResult(
                tool_call["id"], name,
                f"Tool call '{name}' was not approved.",
                is_error=True,
            )
    # outcome == "allow" — fall through to dispatch
    # ─────────────────────────────────────────────────────────────────────

    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
    try:
        result = await fn(**args)
    except Exception as e:
        return ToolResult(tool_call["id"], name, f"Error: {e}", is_error=True)
    return ToolResult(tool_call["id"], name, result)
```

Add the approval prompt helper in `src/agent.py`:

```python
async def _prompt_user(name: str, args: dict) -> bool:
    """Display a permission request and wait for the user's answer.
    Serialised with _prompt_lock so parallel tool calls don't interleave."""
    async with _prompt_lock:
        print(f"\n[PERMISSION REQUEST] Tool: {name}")
        for key, value in args.items():
            preview = str(value)[:200] + ("..." if len(str(value)) > 200 else "")
            print(f"  {key}: {preview}")
        response = await asyncio.to_thread(input, "Allow? [y/N] ")
        return response.strip().lower() == "y"
```

:::tip Why asyncio.Lock for the prompt
The agent dispatches tool calls in parallel via `asyncio.gather`. In `ask` mode, two dangerous tool calls in the same turn would both reach `_prompt_user` concurrently and their `input()` calls would interleave on the terminal — confusing to read and impossible to answer correctly. The `_prompt_lock` ensures only one prompt is shown at a time. Read-only auto-approvals bypass the lock and remain concurrent.
:::

### Step 3 — Configure via environment

No code changes are needed to switch modes — only environment variables:

```bash
# Read-only: write/execute tools are denied without prompting.
AGENT_PERMISSION_MODE=read-only uv run main.py "Summarise the project structure"

# Ask (default): read tools run freely; write/execute tools prompt.
uv run main.py "Add type hints to tools.py"

# Auto: read tools and allowlisted bash commands run freely; everything else is denied.
AGENT_PERMISSION_MODE=auto AGENT_BASH_ALLOWLIST="pytest,git,python" \
    uv run main.py "Run the test suite and report failures"
```

The full list of `AGENT_*` variables is in [Settings Reference](../../operations/settings.md).

## Test it

### Behavior (BDD)

Verify this layer as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Scenario: Permission modes gate write and execute tools correctly
  Given the agent with the PolicyEngine installed in _execute_one_tool

  When AGENT_PERMISSION_MODE=read-only and the agent requests write_file
  Then _execute_one_tool returns ToolResult(is_error=True)
  And the reason contains "read-only mode is active"
  And the write_file function is never called

  When AGENT_PERMISSION_MODE=ask and the agent requests write_file
  And the user types "n" at the approval prompt
  Then _execute_one_tool returns ToolResult(is_error=True)
  And the reason contains "not approved"
  And the write_file function is never called
```

Run this as an integration scenario with the [BDD framework](../../guides/bdd-integration-testing.md).

The scenario fails **before** this layer (both `write_file` calls execute without prompting). After this layer it passes: `read-only` mode denies immediately; `ask` mode surfaces the prompt and respects the user's answer.

## Run it

```bash
# Read-only: the agent can read but write_file is denied.
AGENT_PERMISSION_MODE=read-only uv run main.py "show me what tools.py contains"

# Ask: the agent pauses before writing.
AGENT_PERMISSION_MODE=ask uv run main.py "add a module docstring to tools.py"
# You will see:
# [PERMISSION REQUEST] Tool: write_file
#   path: src/tools.py
#   content: ...
# Allow? [y/N]
```

:::tip Architecture pattern
`PolicyEngine` here is the [Policy Engine](../../architecture-patterns/policy-engine.md) pattern; `AGENT_PERMISSION_MODE` is [Permission Modes](../../architecture-patterns/permission-modes.md) — one switch selecting the rule set over it.
:::

## Recap

The `PolicyEngine` is a single call in `_execute_one_tool` that answers "can this tool call run?" before the tool function is dispatched. Rules compose: `ReadOnlyRule` blocks all writes; `CommandAllowlistRule` delegates to the Layer 12.2 gate; `PathRestrictionRule` denies writes outside the project root. `AGENT_PERMISSION_MODE` selects the rule set and default outcome without touching any other code.

The policy engine controls *what the model is allowed to do*. It does not control *where the agent's file writes land*. If the model makes an edit inside the project that you later want to discard, you need a way to throw it away without affecting your main working tree. That is what Layer 12.4 provides.

→ [Layer 12.4 — Sandboxing](./4-sandboxing.md)
