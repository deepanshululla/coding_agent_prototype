---
sidebar_position: 16
title: Differences from pi.dev
description: Honest mapping of what this project covers vs. pi.dev — what's included, what's intentionally out of scope, and what's planned for later.
---

# Differences from pi.dev

This project is a ground-up implementation of the same agent architecture that pi.dev uses, built for learning rather than production use. The source of truth is Harkirat Singh's "How Modern AI Agents Work Under the Hood" lecture and the pi.dev source code (`github.com/earendil-works/pi`, TypeScript, ~46k stars).

Not everything in pi.dev is in scope here. This page explains what's included, what's deliberately skipped, and what's planned but not yet built.

---

## What this project covers

| Capability | pi.dev location | This project |
|-----------|----------------|-------------|
| Nested inner/outer agent loop | `agent-core` package (~750 lines) | `src/agent.py` |
| 7 core tools (read, write, edit, bash, grep, find, ls) | `packages/tools/` | `src/tools.py` |
| Dynamic system prompt (CWD, date, tool list) | System prompt builder | `src/prompts.py` |
| Parallel tool execution | Default in agent-core | `asyncio.gather` in `src/agent.py` |
| Streaming response handling | Per-provider stream parsers | `src/provider.py` via LiteLLM |
| Multi-provider model support | 40+ provider adapters in `packages/ai/` | LiteLLM (one string swap) |
| CLI entrypoint | `pi` binary | `main.py` + `uv run main.py` |
| Tool error handling (return strings, not exceptions) | Agent loop convention | Enforced by `ToolResult.is_error` |

---

## In scope as supported designs

The core ships today (the table above). Beyond it, these capabilities are **in scope and
fully documented as supported designs** — the architecture has a defined seam for each, and
the docs specify how to wire it in. They are not all merged into `src/` yet, but they are the
project's intended shape, not "maybe someday."

| Capability | pi.dev equivalent | Where it documents | Seam |
|---|---|---|---|
| **Terminal UI (TUI)** | `packages/tui/` | [Terminal UI](./terminal-ui/overview.md) | `AGENT_UI=tui`; an `emit()` event seam over the loop |
| **Keybindings** | TUI config | [Keybindings](./terminal-ui/keybindings.md) | Key → action on the TUI app |
| **Themes** | TUI config | [Themes](./terminal-ui/themes.md) | `AGENT_THEME` + a color-role dict |
| **TUI components** | `packages/tui/src/components/` | [Components](./terminal-ui/components.md) | Each widget driven by an event type |
| **Skills** | System prompt builder | [Skills](./customization/skills.md) | `AGENT_SKILLS` + named blocks composed into the prompt |
| **MCP servers** | MCP client | [MCP](./mcp/overview.md) | `AGENT_MCP_CONFIG`; tools merged into `TOOLS_SCHEMA`/`TOOL_REGISTRY` |
| **Command allowlist** | Permission layer | [Command Allowlist](./operations/command-allowlist.md) | `AGENT_BASH_ALLOWLIST` gate in `_execute_one_tool` |
| **Env-var configuration** | Settings | [Settings](./operations/settings.md) | `AGENT_*` vars via a `src/config.py` reader |
| **Claude CLI LLM backend** | — | [Claude CLI Backend](./customization/claude-cli-backend.md) | `USE_CLAUDE_CLI_LLM=1` routes via `claude -p` |

---

## Still planned (not yet designed in full)

These remain genuinely ahead of the current docs — the loop accommodates them, but the full
design isn't written yet.

| Feature | pi.dev equivalent | Notes |
|---------|------------------|-------|
| **Context compaction / memory** | `transformContext` hook | Add when you hit the 200k token limit; requires token tracking + summarizing old turns. See [Compaction](./advanced/compaction.md). |
| **Steering messages** (mid-run input) | `getSteeringMessages()` | The `pending_messages`/outer-loop plumbing exists; nothing feeds input into it yet. The TUI input box is the natural source. See [Steering](./advanced/steering.md). |
| **Extended thinking** | `thinking` param | One parameter in `stream_response()`; model-specific, adds streaming complexity. See [Extended Thinking](./advanced/extended-thinking.md). |
| **Conversation persistence** | Storage layer | The `messages` list is in-memory; persisting needs a serialization format + backend. See [Sessions](./concepts/sessions.md). |
| **`beforeToolCall` / `afterToolCall` hooks** | Agent loop hooks | The insertion point (`_execute_one_tool`) is defined and used by the allowlist/permission designs; a general hook API is still to come. See [Extensions & Hooks](./customization/extensions-and-hooks.md). |

---

## Still out of scope

| Feature | pi.dev location | Why N/A here |
|---|---|---|
| **Plugin / package system (Pi Packages)** | `packages/` monorepo + npm packaging | This is a single-repo learning project; there's nothing to package or publish. |
| **40+ hand-written provider adapters** | `packages/ai/src/providers/` | Replaced entirely by LiteLLM — one string swaps the model, no per-provider parser. (The [Claude CLI backend](./customization/claude-cli-backend.md) is an additional, optional route.) |

:::note
"Supported design" means the docs specify the seam and the wiring; "planned" means the
architecture accommodates it but the design isn't fully written. See `plans/` for active
implementation plans.
:::

---

## The key simplification: LiteLLM vs. pi's provider layer

Pi.dev's `packages/ai/` is a substantial abstraction: 40+ provider adapters, per-provider streaming event parsers, response normalizers, retry logic, and token counting. It exists because pi was written before LiteLLM was mature enough to trust.

This project replaces that entire layer with:

```python
response = await litellm.acompletion(
    model=MODEL,          # "claude-sonnet-4-5", "gemini/...", "gpt-4o", ...
    messages=full_messages,
    tools=TOOLS_SCHEMA,
    stream=True,
)
```

The tradeoff: you take on a dependency on LiteLLM's OpenAI-format normalization. The gain: zero provider-specific code, and you can swap models by changing one string. For a learning project, this is the right call — understanding the loop is the goal, not understanding Anthropic's raw streaming event format.

---

## Summary

The heart of this project is the agent loop itself — the `while True` that sends messages, streams responses, dispatches tool calls in parallel, and loops. Around that core, the terminal UI, skills, MCP, the command allowlist, env-var configuration, and the Claude CLI backend are supported designs with defined seams. Only packaging (Pi Packages) and pi's hand-written provider adapters are out of scope; compaction, persistence, steering, extended thinking, and a general hook API remain planned.

Pi.dev is a production tool. This project is a transparent implementation of the same core idea, stripped to the minimum needed to understand it.

---

## Related pages

- [FAQ](./faq.md) — why specific design decisions were made
- [Architecture overview](./architecture/overview.md) — how the loop is structured
- [The agent loop](./architecture/the-agent-loop.md) — detailed walkthrough of the inner and outer loops
