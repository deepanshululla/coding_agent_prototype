---
sidebar_position: 6
title: Chain of Responsibility
description: Route an incoming task through an ordered chain of handlers — each decides whether it can deal with the task and which Strategy to use — before handing off to run_agent.
---

# Chain of Responsibility

Not every task deserves the same treatment. A simple question ("what does this function do?") needs a read-only run with no file edits. A PR review needs diff access. An incident-debugging session needs unrestricted `bash`. Wiring all those paths through `if/elif` in `main.py` is fragile. The Chain of Responsibility pattern makes each path an independent handler that can be composed, tested, and extended without touching the others.

:::note Design guidance, not v1
The shipped core passes every task directly to `run_agent`. The chain described here is the seam in front of that call — adopt it once you have more than one meaningfully different task type.
:::

## The problem

As the agent grows, the entry point accumulates logic:

```python
# main.py — what "just adding cases" looks like
if "?" in task:
    run_agent(task, read_only=True)
elif task.startswith("review PR"):
    run_agent(task, diff_only=True)
elif "test failure" in task:
    run_agent(task, strategy=BugFixStrategy())
elif "incident" in task:
    run_agent(task, allow_all=True)
else:
    run_agent(task)
```

Each new task type extends this block. The conditions interact, the ordering matters implicitly, and there is no clean place to add pre/post hooks per type. The Chain of Responsibility pattern replaces this with an explicit, ordered list of handlers, each of which is a small focused object.

## The pattern

Build a linked list (or ordered list) of handler objects. Each handler exposes:

- `can_handle(task: str) -> bool` — does this handler own the task?
- `handle(task: str) -> list[dict]` — run the task and return the message history.

The chain walks the list and stops at the first handler that claims the task. If no handler claims it, a fallback `DefaultHandler` runs.

```
  task string
       │
       ▼
  ┌─────────────────────────┐
  │  SimpleQAHandler        │  can_handle? ─── no ──▶ next
  └──────────┬──────────────┘
             │ yes
             ▼
        handle(task)          ← read-only run_agent, no edits
             │
         (returns)

  (if SimpleQAHandler said no)
       │
       ▼
  ┌─────────────────────────┐
  │  TestFailureHandler     │  can_handle? ─── no ──▶ next
  └──────────┬──────────────┘
             │ yes
             ▼
        handle(task)          ← BugFixStrategy + run_agent
             │
         (returns)

  (… more handlers …)

  ┌─────────────────────────┐
  │  DefaultHandler         │  always returns True
  └──────────┬──────────────┘
             ▼
        handle(task)          ← full run_agent, DefaultStrategy
```

## In this project

The chain sits in front of `run_agent` in `src/agent.py`. Today, `main.py` calls `run_agent(task)` directly. With a chain:

```python
# main.py — with Chain of Responsibility
from chain import build_default_chain

chain = build_default_chain()
messages = await chain.run(task)
```

### The handler protocol

```python
# src/chain.py (planned)
from __future__ import annotations
from typing import Protocol
from strategies import (
    Strategy, DefaultStrategy, BugFixStrategy,
    RefactorStrategy, TestGenerationStrategy,
    ProviderCompatibilityStrategy,
)
from agent import run_agent
from prompts import build_system_prompt
from tools import TOOL_REGISTRY


class Handler(Protocol):
    def can_handle(self, task: str) -> bool: ...
    def handle(self, task: str) -> list[dict]: ...


class Chain:
    def __init__(self, handlers: list[Handler]) -> None:
        self._handlers = handlers

    async def run(self, task: str) -> list[dict]:
        for handler in self._handlers:
            if handler.can_handle(task):
                return await handler.handle(task)
        raise RuntimeError("No handler claimed the task — add a DefaultHandler last.")
```

### Concrete handlers

```python
# src/chain.py (planned, continued)

class SimpleQAHandler:
    """Handles questions that only need reads, not edits."""

    def can_handle(self, task: str) -> bool:
        task_l = task.strip().lower()
        return task_l.endswith("?") or task_l.startswith(("what ", "how ", "why ", "where "))

    async def handle(self, task: str) -> list[dict]:
        # Read-only tool subset; strategy is default (no extra prompt)
        read_only = {k: v for k, v in TOOL_REGISTRY.items()
                     if k in {"read_file", "grep", "find_files", "list_dir"}}
        return await run_agent(task, tool_registry=read_only)


class TestFailureHandler:
    """Handles tasks that look like a failing test or CI failure."""

    def can_handle(self, task: str) -> bool:
        markers = ("test failure", "failing test", "ci failed", "traceback", "assert")
        return any(m in task.lower() for m in markers)

    async def handle(self, task: str) -> list[dict]:
        strategy = BugFixStrategy()
        system_prompt = build_system_prompt(extra=strategy.extra_prompt())
        return await run_agent(task, system_prompt=system_prompt)


class PRReviewHandler:
    """Handles pull-request review tasks — needs diff access but no file writes."""

    def can_handle(self, task: str) -> bool:
        return any(k in task.lower() for k in ("review pr", "review pull request", "code review"))

    async def handle(self, task: str) -> list[dict]:
        # PR review: read + bash (for git diff), but not write_file / edit_file
        review_tools = {k: v for k, v in TOOL_REGISTRY.items()
                        if k not in {"write_file", "edit_file"}}
        extra = (
            "## PR-review mode\n"
            "Use `bash` with `git diff` to read the diff. "
            "Do not edit any files. Produce a structured review: "
            "correctness issues, style suggestions, missing tests."
        )
        system_prompt = build_system_prompt(extra=extra)
        return await run_agent(task, system_prompt=system_prompt,
                               tool_registry=review_tools)


class IncidentHandler:
    """Handles live-incident and debugging tasks that need unrestricted access."""

    def can_handle(self, task: str) -> bool:
        markers = ("incident", "outage", "prod is down", "debug", "investigate")
        return any(m in task.lower() for m in markers)

    async def handle(self, task: str) -> list[dict]:
        extra = (
            "## Incident-debugging mode\n"
            "Time matters. Start by reading recent logs or running the command "
            "that surfaces the error. Narrow the blast radius before making any edits."
        )
        system_prompt = build_system_prompt(extra=extra)
        return await run_agent(task, system_prompt=system_prompt)


class ProviderCompatibilityHandler:
    """Handles LiteLLM / model-adapter compatibility checks."""

    def can_handle(self, task: str) -> bool:
        markers = ("litellm", "provider", "adapter", "model compat", "switch model")
        return any(m in task.lower() for m in markers)

    async def handle(self, task: str) -> list[dict]:
        strategy = ProviderCompatibilityStrategy()
        system_prompt = build_system_prompt(extra=strategy.extra_prompt())
        return await run_agent(task, system_prompt=system_prompt)


class DefaultHandler:
    """Catch-all — always claims the task, uses the full tool registry."""

    def can_handle(self, task: str) -> bool:
        return True

    async def handle(self, task: str) -> list[dict]:
        return await run_agent(task)


def build_default_chain() -> Chain:
    return Chain([
        SimpleQAHandler(),
        TestFailureHandler(),
        PRReviewHandler(),
        IncidentHandler(),
        ProviderCompatibilityHandler(),
        DefaultHandler(),   # must be last
    ])
```

### Handler ordering matters

The chain is evaluated top-to-bottom; the first `can_handle` returning `True` wins. Put narrow, high-confidence matchers first and the catch-all last. If two handlers could both claim a task (e.g., a PR review that also involves a failing test), the earlier one wins — design `can_handle` so that the more specialized handler appears first.

### Pairing with Strategy

Each handler's `handle` method decides which [Strategy](./strategy-pattern.md) to apply. The two patterns are complementary:

- The **handler** answers "who owns this task?" (routing).
- The **strategy** answers "how should this task be run?" (behavior).

A handler can delegate strategy selection to `Strategy.select(task)` for simple cases, or hard-code a specific strategy when the handler's classification already implies the behavior.

## Trade-offs

| | Benefit | Cost |
|---|---|---|
| **Open/closed** | Add a new task type by adding a handler, no core edits | The chain must be re-ordered carefully when cases overlap |
| **Testability** | Each handler's `can_handle` and `handle` are independently testable | Means writing more test cases (one per handler) |
| **Transparency** | Easy to log which handler claimed a task | Classification failures are silent without explicit logging |
| **Composability** | Handlers can delegate to other handlers or sub-chains | Nested chains get confusing quickly; keep it flat |
| **Short-circuit** | Early handlers block later ones | A misclassification sends the task to the wrong handler |

The biggest operational risk is `can_handle` keyword matching silently misfiring. Mitigations: log the chosen handler name at the start of each run, expose a `--dry-classify` flag that prints the handler without running the agent, and keep `DefaultHandler` permissive enough that a misclassified task still succeeds (it just may be slightly under-optimized).

## Related

- [Strategy Pattern](./strategy-pattern.md) — handlers select strategies; read this alongside.
- [State Machine](./state-machine.md) — once a handler claims the task, the state machine controls the execution flow.
- [Planner / Executor Split](./planner-executor.md) — a handler can instantiate separate planner and executor agents instead of a single `run_agent` call.
