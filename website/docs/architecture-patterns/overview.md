---
sidebar_position: 1
title: Overview
description: A catalog of the software architecture patterns that scale a coding agent from a small loop to a maintainable system, and how each one maps onto this project.
slug: /architecture-patterns
---

# Architecture Patterns

The [agent loop](../architecture/the-agent-loop.md) is deliberately ~750 lines: one `while`, a tool registry, a provider call. That smallness is the point of the [tutorial](../tutorial/overview.md). But the moment an agent grows past a toy — more tools, more providers, real safety requirements, auditability, multi-step plans — a handful of classic patterns keep it maintainable instead of letting it rot into a tangle of `if` statements.

This section catalogs those patterns. Each page explains the pattern, **why a coding agent needs it**, how it maps onto *this* project's code, a concrete sketch, and the trade-offs.

:::note These are guidance, not v1
The shipped core is intentionally simpler than most of these patterns. Each page is an architectural recommendation for when you outgrow the core — it names the exact seam in `src/` where the pattern slots in. Adopt them as the need appears, not preemptively.
:::

## The catalog

| Pattern | The problem it solves | Where it touches this project |
|---|---|---|
| [Plugin Architecture](./plugin-architecture.md) | Add GitHub, Jira, Slack, K8s tools without editing the core | `TOOL_REGISTRY` / `TOOLS_SCHEMA` in `tools.py` |
| [Ports & Adapters (Hexagonal)](./ports-and-adapters.md) | The core shouldn't know if it's on GitHub or GitLab, Postgres or memory | `provider.py` is already an `LLMPort`; generalize it |
| [Command Pattern](./command-pattern.md) | Make every tool call a first-class object: log, replay, audit, undo | `_execute_one_tool` → a `Command` |
| [Strategy Pattern](./strategy-pattern.md) | Different behavior per task type (bug fix vs refactor vs upgrade) | The system prompt + tool set selection |
| [Chain of Responsibility](./chain-of-responsibility.md) | Route an incoming task to the handler that can deal with it | A classifier in front of `run_agent` |
| [State Machine](./state-machine.md) | Stop the agent wandering: explicit GATHER → PLAN → EDIT → TEST → DONE | The inner loop's phases become states |
| [Event Sourcing / Run Log](./event-sourcing.md) | An append-only record of every decision and result for debug/eval/replay | The `messages` list, generalized to an event stream |
| [Policy Engine / Guards](./policy-engine.md) | Decide "can this run?" *outside* the LLM, deterministically | `_execute_one_tool` gate; the [command allowlist](../operations/command-allowlist.md) |
| [Planner / Executor Split](./planner-executor.md) | Separate "decide the plan" from "carry it out" for control and review | Two roles over one `run_agent` |
| [Worktrees](./worktrees.md) | Isolate the agent's edits so it can't corrupt your working tree | A `SandboxPort` adapter around `bash`/file tools |
| [Permission Modes](./permission-modes.md) | One switch for read-only / ask / auto across all tools | `AGENT_PERMISSION_MODE` over the policy engine |

## How they compose

These patterns aren't alternatives — they layer. A production agent typically stacks them like this:

```
            ┌──────────────────────────────────────────────┐
   task →   │  Chain of Responsibility  (route the task)   │
            └───────────────────────┬──────────────────────┘
                                    ▼
            ┌──────────────────────────────────────────────┐
            │  Strategy        (pick behavior for the type) │
            └───────────────────────┬──────────────────────┘
                                    ▼
            ┌──────────────────────────────────────────────┐
            │  Planner / Executor   (decide, then do)       │
            │   State Machine       (GATHER→PLAN→EDIT→…)     │
            └───────────────────────┬──────────────────────┘
                                    ▼ every action is a …
            ┌──────────────────────────────────────────────┐
            │  Command  ──guarded by──▶  Policy Engine       │
            │     │                       (+ Permission Mode)│
            │     ▼ dispatched to a …                        │
            │  Plugin (tool)  ──runs through──▶  Ports/Adapters
            │     │                              (Sandbox/Repo/LLM)
            │     ▼ recorded in …                            │
            │  Event Log  (append-only, replayable)          │
            └──────────────────────────────────────────────┘
```

Read top-to-bottom: a task is **routed** (Chain of Responsibility) to a **strategy**, which runs a **planner/executor** driven by a **state machine**; each step is a **command**, checked by the **policy engine** under the active **permission mode**, dispatched to a **plugin** tool that reaches the outside world through **ports/adapters** (with edits isolated in a **worktree**), and every event is appended to the **run log**.

## Where to start

If you adopt only three, adopt these — they give the most safety and extensibility for the least code:

1. **[Plugin Architecture](./plugin-architecture.md)** — you'll add tools constantly; make it a registry, not a core edit.
2. **[Policy Engine + Permission Modes](./policy-engine.md)** — the agent runs `bash`; deterministic guards are non-negotiable.
3. **[Ports & Adapters](./ports-and-adapters.md)** — the one decision that keeps the core testable and provider-agnostic (LiteLLM already proves it for the LLM port).

The tutorial points at the relevant pattern as each concept is introduced — see [Phase 6](../tutorial/06-a-toolbox.md), [Phase 11](../tutorial/11-add-litellm.md), [Phase 12](../tutorial/12-harden-it/1-security-model.md), and [Phase 18](../tutorial/18-go-further.md).
