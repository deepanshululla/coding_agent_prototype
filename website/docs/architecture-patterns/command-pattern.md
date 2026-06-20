---
sidebar_position: 4
title: Command Pattern
description: Reify every tool call as a first-class Command object to unlock logging, replay, audit trails, approval gates, and selective undo.
---

# Command Pattern

Every time the agent calls a tool it issues a *command*: run this shell command, apply this patch, search this repository. Right now those intents evaporate the moment the async function returns. The Command Pattern keeps them alive as first-class objects — and that single change unlocks logging, replay, audit, approvals, and undo without invasive rewrites of the loop.

## The problem

`_execute_one_tool` in `agent.py` is three lines:

```python
async def _execute_one_tool(tool_call: dict) -> ToolResult:
    name = tool_call["name"]
    args = tool_call["input"]
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
    result = await fn(**args)
    return ToolResult(tool_call["id"], name, result)
```

There is no record that a call happened beyond the result string appended to `messages`. You cannot:

- **audit** which shell commands ran during a session
- **replay** a failed run from a checkpoint without re-executing the LLM calls
- **ask for approval** before a destructive operation (`write_file`, `bash` with `rm`)
- **undo** an edit (`edit_file`) if the agent takes a wrong turn

All of these require the tool call to be a value you can inspect, store, and act on *before and after* execution.

## The pattern

Reify each tool invocation as a **Command** object with three responsibilities:

1. **Describe** itself (`describe()`) — a human-readable summary for logs and approval prompts.
2. **Execute** itself (`execute()`) — carries out the action, returns a `ToolResult`.
3. **Undo** itself (`undo()`) — optional; reverses the action if possible.

The dispatcher (`_execute_one_tool`) becomes a thin factory: it builds the right `Command` subclass for the tool name, then hands it to a `CommandRunner` that handles logging, approval, and execution.

```
  agent loop
      │
      ▼
  _execute_one_tool(tool_call)
      │
      ▼ builds
  Command  ──► describe() → logged, possibly shown to user for approval
      │
      ▼ execute() ──► ToolResult
      │
      ▼ (if is_error or agent backtracks) undo()
      │
      ▼
  CommandLog (append-only)
```

## In this project

:::note Planned pattern, not yet shipped
`_execute_one_tool` dispatches through `TOOL_REGISTRY` directly today. The refactor below is a recommended step when you need audit trails or approval gates. The `ToolResult` type from `src/types_.py` is already the return type and doesn't change.
:::

**Step 1 — Define the `Command` base**

```python
# src/command.py
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.types_ import ToolResult


@dataclass
class Command(ABC):
    tool_call_id: str
    tool_name: str
    args: dict
    issued_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @abstractmethod
    def describe(self) -> str:
        """One human-readable line for logs and approval prompts."""

    @abstractmethod
    async def execute(self) -> ToolResult:
        """Carry out the action. Never raises — errors go in ToolResult."""

    async def undo(self) -> str | None:
        """Reverse the action. Return None if undo is not supported."""
        return None
```

**Step 2 — Concrete command classes for each tool**

```python
# src/commands/run_shell.py
from src.command import Command
from src.tools import bash
from src.types_ import ToolResult


class RunShellCommand(Command):
    """Wraps the `bash` tool."""

    def describe(self) -> str:
        return f"bash: {self.args.get('command', '')}"

    async def execute(self) -> ToolResult:
        result = await bash(**self.args)
        is_error = result.startswith("Error:")
        return ToolResult(self.tool_call_id, self.tool_name, result, is_error=is_error)

    # Shell commands are generally not undoable — leave undo() returning None.
```

```python
# src/commands/apply_patch.py
from pathlib import Path
from src.command import Command
from src.tools import edit_file
from src.types_ import ToolResult


class ApplyPatchCommand(Command):
    """Wraps the `edit_file` tool; stores the original text for undo."""

    _original: str | None = None

    def describe(self) -> str:
        path = self.args.get("path", "")
        old = self.args.get("old_string", "")[:40]
        return f"edit_file {path!r}: replace {old!r}…"

    async def execute(self) -> ToolResult:
        path = self.args.get("path", "")
        try:
            self._original = Path(path).read_text()
        except Exception:
            self._original = None
        result = await edit_file(**self.args)
        is_error = result.startswith("Error:")
        return ToolResult(self.tool_call_id, self.tool_name, result, is_error=is_error)

    async def undo(self) -> str | None:
        if self._original is None:
            return "Cannot undo: original content not captured."
        path = self.args.get("path", "")
        try:
            Path(path).write_text(self._original)
            return f"Reverted {path}"
        except Exception as e:
            return f"Error reverting {path}: {e}"
```

```python
# src/commands/search_repo.py
from src.command import Command
from src.tools import grep
from src.types_ import ToolResult


class SearchRepoCommand(Command):
    """Wraps the `grep` tool."""

    def describe(self) -> str:
        pattern = self.args.get("pattern", "")
        path = self.args.get("path", ".")
        return f"grep {pattern!r} in {path}"

    async def execute(self) -> ToolResult:
        result = await grep(**self.args)
        return ToolResult(self.tool_call_id, self.tool_name, result)

    # Read-only; undo is a no-op.
```

**Step 3 — A factory that maps tool name → `Command` subclass**

```python
# src/command_factory.py
from src.command import Command
from src.commands.run_shell import RunShellCommand
from src.commands.apply_patch import ApplyPatchCommand
from src.commands.search_repo import SearchRepoCommand

# Extend this dict as you add more command types.
_COMMAND_MAP: dict[str, type[Command]] = {
    "bash": RunShellCommand,
    "edit_file": ApplyPatchCommand,
    "grep": SearchRepoCommand,
    "find_files": SearchRepoCommand,   # same shape
}

_DEFAULT_COMMAND_CLASS: type[Command] = RunShellCommand   # fallback


def build_command(tool_call: dict) -> Command:
    cls = _COMMAND_MAP.get(tool_call["name"], _DEFAULT_COMMAND_CLASS)
    return cls(
        tool_call_id=tool_call["id"],
        tool_name=tool_call["name"],
        args=tool_call["input"],
    )
```

**Step 4 — Refactor `_execute_one_tool` to dispatch via commands**

The agent loop (`agent.py`) gains a `CommandLog` and calls `build_command`:

```python
# src/agent.py  (updated)
from src.command_factory import build_command

_command_log: list[Command] = []   # grows for the lifetime of the run


async def _execute_one_tool(tool_call: dict) -> ToolResult:
    cmd = build_command(tool_call)

    # ── Optional: approval gate ──────────────────────────────────────────
    # from src.policy import should_approve
    # if should_approve(cmd):
    #     approved = await ask_user(f"Allow: {cmd.describe()}? [y/N] ")
    #     if not approved:
    #         return ToolResult(cmd.tool_call_id, cmd.tool_name,
    #                           "User denied.", is_error=True)

    print(f"  ▸ {cmd.describe()}")
    result = await cmd.execute()
    _command_log.append(cmd)
    print(f"  [✓ {cmd.tool_name}: {len(result.content)} chars]")
    return result
```

The log line where `_command_log.append(cmd)` sits is exactly where [event sourcing](./event-sourcing.md) plugs in — emit the command to a persistent event stream and you have a replayable run record.

**Undo a sequence of commands**

```python
async def undo_last_n(n: int) -> list[str]:
    """Undo the last n commands in reverse order."""
    to_undo = _command_log[-n:][::-1]
    results = []
    for cmd in to_undo:
        msg = await cmd.undo()
        results.append(msg or f"{cmd.tool_name}: undo not supported")
    return results
```

**`CreatePullRequestCommand` — a network command with no undo**

```python
# src/commands/create_pr.py
from src.command import Command
from src.types_ import ToolResult


class CreatePullRequestCommand(Command):
    def describe(self) -> str:
        return (
            f"create PR in {self.args.get('repo', '?')}: "
            f"{self.args.get('title', '')}"
        )

    async def execute(self) -> ToolResult:
        # calls the github plugin (see plugin-architecture.md)
        from tools.github.plugin import create_pull_request
        result = await create_pull_request(**self.args)
        return ToolResult(self.tool_call_id, self.tool_name, result)

    async def undo(self) -> str | None:
        # PRs can be closed but not truly deleted via the API
        return "Cannot undo: PR creation is permanent."
```

This is also where the [policy engine](./policy-engine.md) slots in — `CreatePullRequestCommand.describe()` gives the guard a structured description to match against an allowlist before any network call happens.

## Trade-offs

| | Command Pattern | Direct dispatch (current) |
|---|---|---|
| **Audit trail** | Every command is a logged object | Only the string result survives |
| **Undo** | Opt-in per command class | Not possible without re-architecting |
| **Approval gates** | Natural — inspect before execute | Requires awkward wrapping |
| **Replay** | Serialize and re-execute the log | Impossible without the LLM |
| **Complexity** | One class per tool + a factory | Three lines in `_execute_one_tool` |
| **Right time to adopt** | When you need audit, approvals, or undo | While the tool set is small and stable |

The smallest useful slice is: add `Command`, implement `RunShellCommand` and `ApplyPatchCommand` only (the highest-risk tools), and log them. Skip the undo machinery until a specific use case demands it. The factory and the loop change are the same either way.

:::warning Undo is harder than it looks
File-level undo (`edit_file`, `write_file`) is straightforward — save the original and restore it. Shell command undo is generally impossible: you can't un-run `git push` or un-delete a file that wasn't tracked. Mark those commands' `undo()` as unsupported from the start, and make that explicit in approval prompts.
:::

## Related

- [Parallel tool execution](../tools/parallel-execution.md)
- [Event Sourcing / Run Log](./event-sourcing.md)
- [Policy Engine](./policy-engine.md)
