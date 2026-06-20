---
sidebar_position: 9
title: Policy Engine / Guards
description: A deterministic, code-level gate that answers "can this tool call run?" before the LLM's request is dispatched — composing command allowlists, path restrictions, secret guards, and approval rules outside the model's influence.
---

# Policy Engine / Guards

Before the agent executes a dangerous tool call, one question must be answered: **is this
allowed?** The policy engine answers that question deterministically, in code, before the tool
runs. The LLM cannot talk its way past it.

:::note Design guidance, not v1
The shipped core executes every tool call without a policy check (see
[Permissions & Gating](../operations/permissions.md)). The gate point in `_execute_one_tool`
is well-defined and this pattern slots in without changing the rest of the loop. Add it as
safety requirements grow.
:::

## The problem

The LLM chooses which tools to call and with what arguments. It can be wrong, confused, or
manipulated via prompt injection. A model that has been told "you can only read files" can still
emit a `write_file` tool call — the model is not the guard, the code is.

Without a policy layer:
- `bash` runs every command the model requests, including `rm -rf`, `curl | sh`, and network
  exfiltration commands.
- `write_file` can overwrite files outside the project, including system files if the process
  has the permissions.
- `read_file` can pull in `.env` files and secrets, which then appear in the message history
  sent to the model's API provider.

The policy engine is the answer. It is not a prompt. It is not a system message. It is a
function that returns `allow`, `deny`, or `ask` — and the result is enforced by the dispatcher,
not by the model.

## The pattern

A `PolicyEngine` composes rules into a single `check()` call. The result is a typed `Decision`.
The dispatcher (`_execute_one_tool`) calls `check()` before dispatching the tool function and
returns the denial as a `ToolResult` with `is_error=True` if the decision is not `allow`.

```
  LLM tool call request
          │
          ▼
  ┌───────────────────┐
  │  _execute_one_tool │
  │                   │
  │  PolicyEngine     │
  │  .check(call)     │
  │    │              │
  │    ├─ ALLOW ──────────────────────▶  dispatch to tool fn
  │    │              │                  (bash, write_file, …)
  │    ├─ ASK ────────────────────────▶  prompt user → allow / deny
  │    │              │
  │    └─ DENY ───────────────────────▶  ToolResult(is_error=True)
  │                   │                  (model reads the reason and adapts)
  └───────────────────┘
```

The key property: **DENY is a `ToolResult`, not an exception.** Tools never raise
(see [Error Handling](../tools/error-handling.md)). A denied call returns a descriptive error
string to the model, which reads it, adjusts, and tries again — or asks the user.

## In this project

The gate point is `_execute_one_tool` in `src/agent.py`. Today it dispatches immediately after
a registry lookup. The policy engine slots in between the args extraction and the `fn(**args)`
call — the `beforeToolCall` position described in
[Permissions & Gating](../operations/permissions.md):

```python
# src/agent.py — current v1 (no policy gate)
async def _execute_one_tool(tool_call: dict) -> ToolResult:
    name = tool_call["name"]
    args = tool_call["input"]
    print(f"  [executing {name} {args}]")
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
    try:
        result = await fn(**args)
    except Exception as e:
        return ToolResult(tool_call["id"], name, f"Error: {e}", is_error=True)
    return ToolResult(tool_call["id"], name, result)
```

With a policy engine inserted:

```python
# src/agent.py — with policy gate (planned extension)
from policy import PolicyEngine, Decision

_policy = PolicyEngine.from_env()   # reads AGENT_PERMISSION_MODE, allowlist config, etc.

async def _execute_one_tool(tool_call: dict) -> ToolResult:
    name = tool_call["name"]
    args = tool_call["input"]

    # ── Policy gate: runs before any tool dispatch ────────────────────────
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
    # outcome == "allow" falls through
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

### The `PolicyEngine` and `Decision` types

```python
# src/policy.py (planned extension)
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal


@dataclass
class Decision:
    outcome: Literal["allow", "deny", "ask"]
    reason: str = ""


class PolicyEngine:
    """Composes rules into a single check() call.

    Rules are evaluated in order. The first matching rule wins.
    If no rule matches, the default outcome applies (typically "ask" or "deny").
    """

    def __init__(self, rules: list[Rule], default: Literal["allow", "deny", "ask"] = "ask"):
        self.rules = rules
        self.default = default

    @classmethod
    def from_env(cls) -> PolicyEngine:
        """Build an engine from environment variables and config files."""
        import os
        mode = os.environ.get("AGENT_PERMISSION_MODE", "ask")
        return cls(
            rules=_load_rules(mode),
            default="allow" if mode == "auto" else "deny" if mode == "read-only" else "ask",
        )

    def check(self, tool_name: str, args: dict) -> Decision:
        for rule in self.rules:
            decision = rule.evaluate(tool_name, args)
            if decision is not None:
                return decision
        return Decision(outcome=self.default, reason="no matching rule; default applied")
```

### Composing rules

A `Rule` is a callable that inspects `(tool_name, args)` and returns a `Decision` or `None`
(pass-through to the next rule). The engine evaluates them in order; the first non-`None`
result wins.

```python
# src/policy.py (continued)
from abc import ABC, abstractmethod

class Rule(ABC):
    @abstractmethod
    def evaluate(self, tool_name: str, args: dict) -> Decision | None:
        ...


class ReadOnlyRule(Rule):
    """Deny all write and execute tools unconditionally."""
    WRITE_EXECUTE = {"bash", "write_file", "edit_file"}

    def evaluate(self, tool_name: str, args: dict) -> Decision | None:
        if tool_name in self.WRITE_EXECUTE:
            return Decision("deny", f"'{tool_name}' is a write/execute tool; read-only mode is active")
        return None  # pass through for read-only tools


class CommandAllowlistRule(Rule):
    """Apply the command allowlist to bash calls (see command-allowlist.md)."""

    def evaluate(self, tool_name: str, args: dict) -> Decision | None:
        if tool_name != "bash":
            return None
        from allowlist import check_command  # the Verdict-returning function
        verdict = check_command(args.get("command", ""))
        if not verdict.allowed:
            return Decision("deny", verdict.reason)
        return Decision("allow")  # allowlisted — no need to ask


class PathRestrictionRule(Rule):
    """Deny file writes outside the allowed root."""

    def __init__(self, allowed_root: str):
        import pathlib
        self.root = pathlib.Path(allowed_root).resolve()

    def evaluate(self, tool_name: str, args: dict) -> Decision | None:
        if tool_name not in {"write_file", "edit_file"}:
            return None
        import pathlib
        try:
            resolved = pathlib.Path(args.get("path", "")).resolve()
            if not resolved.is_relative_to(self.root):
                return Decision("deny", f"path {resolved} is outside allowed root {self.root}")
        except ValueError:
            return Decision("deny", "could not resolve path")
        return None  # path is safe; let other rules decide


class SecretGuardRule(Rule):
    """Deny reads of known secret files."""
    SECRET_PATTERNS = {".env", ".env.local", "credentials.json", ".netrc"}

    def evaluate(self, tool_name: str, args: dict) -> Decision | None:
        if tool_name != "read_file":
            return None
        import pathlib
        name = pathlib.Path(args.get("path", "")).name
        if name in self.SECRET_PATTERNS:
            return Decision("deny", f"reading '{name}' is not permitted; it may contain secrets")
        return None


class PluginPermissionRule(Rule):
    """Honour the permission_level declared by a plugin tool.

    A plugin that declares permission_level="dangerous" gets an "ask" outcome
    unless the active mode is "auto" and it passed the allowlist.
    """

    def __init__(self, plugin_levels: dict[str, str], mode: str):
        self.levels = plugin_levels   # tool_name → "safe" | "dangerous" | "restricted"
        self.mode = mode

    def evaluate(self, tool_name: str, args: dict) -> Decision | None:
        level = self.levels.get(tool_name)
        if level is None:
            return None  # not a plugin tool
        if level == "safe":
            return Decision("allow")
        if level == "restricted":
            return Decision("deny", f"plugin '{tool_name}' is restricted in this environment")
        # level == "dangerous"
        if self.mode == "auto":
            return None  # let the allowlist rule decide
        return Decision("ask", f"plugin '{tool_name}' requires approval (permission_level=dangerous)")
```

### Assembling the engine

```python
# src/policy.py (continued)
import os

def _load_rules(mode: str) -> list[Rule]:
    rules: list[Rule] = []

    if mode == "read-only":
        rules.append(ReadOnlyRule())
        return rules   # nothing else matters in read-only mode

    rules.append(SecretGuardRule())
    rules.append(CommandAllowlistRule())
    rules.append(PathRestrictionRule(allowed_root=os.getcwd()))

    plugin_levels = _load_plugin_levels()   # from plugin registry metadata
    rules.append(PluginPermissionRule(plugin_levels=plugin_levels, mode=mode))

    return rules
```

The order is: **secrets first** (never exposed), then **command allowlist** (specific and
deterministic), then **path restrictions** (blast-radius control), then **plugin levels**
(per-tool declaration). A rule returning `None` passes control to the next one; returning a
`Decision` short-circuits the rest.

## Trade-offs

| | Benefit | Cost |
|---|---|---|
| **Code, not prompt** | The guard is deterministic — the model cannot argue past it | Requires a rule for every new capability; gaps default to the engine's default outcome |
| **Composable rules** | Each rule is independently testable; new rules don't touch existing ones | Rule ordering matters — document it |
| **deny → ToolResult** | The model recovers gracefully; it reads the reason and adapts | A bad denial reason ("denied") causes the model to guess; good reasons ("'rm' not in allowlist; use 'git clean'") cause it to adapt |
| **ask → stdin prompt** | Human stays in the loop for ambiguous calls | `input()` blocks the event loop; use an `asyncio.Lock` for the prompt path so parallel tool calls don't interleave their prompts (see [Permissions & Gating](../operations/permissions.md)) |
| **Single gate point** | `_execute_one_tool` is the only place to update | If a future refactor splits dispatch, the gate must move with it |

:::warning The guard is code, not a prompt
Adding "never run rm -rf" to the system prompt is not a safety control. The model might ignore
it under adversarial input, unusual phrasing, or a multi-step distraction. The only reliable
guard is a function that evaluates the actual tool call arguments — not the model's stated
intentions — and enforces the outcome.
:::

## Related

- [Command Allowlist](../operations/command-allowlist.md) — the deep dive on safe allowlisting of `bash`, including shell-parsing traps
- [Permissions & Gating](../operations/permissions.md) — the `beforeToolCall` hook this builds on; simpler per-tool gating
- [Security Model](../operations/security.md) — the threat model that motivates deterministic guards
- [Permission Modes](./permission-modes.md) — the single environment-variable switch (`read-only` / `ask` / `auto`) that controls the engine's default behavior
- [Command Pattern](./command-pattern.md) — turning each tool call into a first-class object; the `Command` is what the policy engine checks
- [Plugin Architecture](./plugin-architecture.md) — how plugins declare their `permission_level` so the engine can apply the right rule
