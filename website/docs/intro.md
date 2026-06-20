---
sidebar_position: 1
title: Introduction
description: What this project is, the mental model of a coding agent, and how the docs are organized.
slug: /intro
---

# Coding Agent From Scratch

A coding agent is not a framework. It is a **loop**: send the conversation to a model,
let the model call tools, feed the results back, and repeat until the model says it is
done. This project builds that loop in plain Python — under ~750 lines, the same shape
that production agents like [pi.dev](https://pi.dev) ship — so you can see exactly how the
magic works with nothing hidden behind a library.

:::info Grounded in two sources
The design here is distilled from Harkirat Singh's Super 30 lecture
*"How Modern AI Agents Work Under the Hood"* and the [pi.dev source code](https://github.com/earendil-works/pi)
(TypeScript, ~46k stars). LiteLLM stands in for pi's 40-provider abstraction layer so the
core stays small.
:::

## The mental model

Everything in this codebase exists to serve one nested loop.

```
User task
   │
   ▼
┌──────────────────────────────────────────┐
│              OUTER LOOP                   │  ← handles follow-up messages
│  ┌────────────────────────────────────┐  │
│  │           INNER LOOP               │  │  ← the core agent loop
│  │  sendMessage → stream response     │  │
│  │  if tool_calls → execute all       │  │
│  │  push results → continue           │  │
│  │  if end_turn  → break inner        │  │
│  └────────────────────────────────────┘  │
│  if follow-up messages → continue outer   │
│  else → break outer                       │
└──────────────────────────────────────────┘
```

- The **inner loop** is the agent: stream a response, execute any tool calls the model
  requested (in parallel), append the results to the conversation, and go again. It ends
  when the model returns text with no tool calls.
- The **outer loop** exists only to handle *follow-up messages* — anything the user queues
  after the agent would otherwise stop.

That's the whole idea. LangChain and LangGraph just package this abstraction; here you
own it. See **[The Agent Loop](./architecture/the-agent-loop.md)** for the line-by-line
walkthrough.

## What you get

| Piece | One-liner | Where |
|---|---|---|
| The loop | Inner tool-call cycle + outer follow-up loop | [Architecture](./architecture/overview.md) |
| 7 tools | `read`, `write`, `edit`, `bash`, `grep`, `find`, `ls` | [Tools](./tools/overview.md) |
| Provider layer | One LiteLLM call → any of 40+ providers | [Provider Layer](./architecture/provider-layer.md) |
| Streaming | Accumulate OpenAI-format chunks into tool calls | [Streaming & Events](./architecture/streaming-and-events.md) |
| System prompt | Built dynamically from CWD, date, tool list | [System Prompts](./concepts/system-prompts.md) |

## How these docs are organized

1. **[Getting Started](./getting-started/quickstart.md)** — install, configure a key, run your first task.
2. **[Architecture](./architecture/overview.md)** — the loop, streaming, message types, provider layer.
3. **[Tools](./tools/overview.md)** — the schema format, the seven built-ins, parallel execution, and writing your own.
4. **[Core Concepts](./concepts/system-prompts.md)** — prompts, the context window, async, sessions.
5. **[MCP](./mcp/overview.md)** — connect external tool servers and merge their tools into the registry.
6. **[Customization](./customization/prompt-templates.md)** — prompt templates, hooks, skills, custom models/providers, the [Claude CLI backend](./customization/claude-cli-backend.md).
7. **[Terminal UI](./terminal-ui/overview.md)** — an opt-in full-screen interface over the same loop.
8. **[Operations](./operations/security.md)** — security, [command allowlist](./operations/command-allowlist.md), settings, permissions.
9. **[Programmatic Usage](./programmatic-usage/sdk.md)** — embed the agent, RPC, JSON event stream.
10. **[Guides](./guides/swapping-providers.md)**, **[Advanced](./advanced/steering.md)**, **[Reference](./reference/agent.md)**, and **[Contributing](./contributing/development-workflow.md)**.

:::note Implementation status
The core is **implemented and tested**: `src/types_.py`, `src/tools.py` (all 7 tools),
`src/prompts.py`, `src/provider.py`, `src/agent.py`, and `main.py`, with unit tests for the
tools and mocked-model integration tests for the loop (`tests/`). Several larger capabilities —
the [Terminal UI](./terminal-ui/overview.md), [Skills](./customization/skills.md),
[MCP](./mcp/overview.md), the [command allowlist](./operations/command-allowlist.md),
[env-var configuration](./operations/settings.md), and the
[Claude CLI backend](./customization/claude-cli-backend.md) — are **supported designs**: the
docs specify the seam and the wiring, and they're being layered onto the core. A few
features (context compaction, steering input, extended thinking, session persistence, a
general hook API) are **planned** but not yet fully designed. Each page says where it stands.
See **[Differences from pi.dev](./differences-from-pi.md)** for the full map.
:::

## Next step

Head to the **[Quickstart](./getting-started/quickstart.md)** to get the agent running in
about five minutes, or jump straight to **[The Agent Loop](./architecture/the-agent-loop.md)**
if you want the theory first.
