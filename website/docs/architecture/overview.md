---
sidebar_position: 1
title: Overview
description: The complete system on one page — file layout, module responsibilities, and how data flows from task to LLM to tools and back.
---

# Overview

This project is a minimal coding agent built from first principles. The goal is to understand exactly what a coding agent is — not through a framework that hides the details, but by reading the loop itself. The entire agent core is fewer than 200 lines.

:::note
The `src/*.py` files described here are fully implemented. The descriptions and code snippets below reflect the shipped code.
:::

## File layout

```
coding_agent_from_scratch/
├── src/
│   ├── agent.py         # The while-loop (inner + outer), streaming, tool dispatch
│   ├── tools.py         # 7 tool definitions (schema dicts) + async implementations
│   ├── prompts.py       # System prompt builder (dynamic: CWD, date, tool list)
│   ├── provider.py      # LiteLLM wrapper — one async stream_response() function
│   └── types_.py        # Dataclasses for ToolCall, ToolResult, Message
├── tests/
│   ├── test_tools.py    # Unit tests for each tool function
│   └── test_agent.py    # Integration tests for the agent loop (mock LLM)
├── main.py              # CLI entrypoint — asyncio.run(run_agent(task))
├── pyproject.toml
└── .env                 # ANTHROPIC_API_KEY=sk-...
```

The `src/` directory is intentionally not a Python package (no `__init__.py`). Add it to the path via `pyproject.toml` under `[tool.pytest.ini_options]` with `pythonpath = ["src"]`, or prepend it to `sys.path` in `main.py`.

## What each module owns

| Module | Responsibility |
|--------|---------------|
| `agent.py` | The nested outer/inner loop; streaming accumulation; parallel tool dispatch |
| `tools.py` | OpenAI-style JSON schemas for 7 tools; async `async def` implementations; `TOOL_REGISTRY` dict |
| `prompts.py` | `build_system_prompt()` — injects current working directory and today's date |
| `provider.py` | `stream_response()` — one call to `litellm.acompletion(stream=True)`; yields OpenAI-format chunks |
| `types_.py` | `ToolCall`, `ToolResult`, `Message` dataclasses; named `types_` to avoid shadowing stdlib `types` |
| `main.py` | CLI parsing; `load_dotenv()`; `asyncio.run(run_agent(task))` |

## How data flows

```
User task (string)
       │
       ▼
  main.py ──► run_agent(task)
                   │
                   ▼
           ┌──────────────────────────────────────────┐
           │              OUTER LOOP                  │  ← handles follow-up messages
           │  ┌────────────────────────────────────┐  │
           │  │           INNER LOOP               │  │  ← the core agent loop
           │  │  stream_response() → chunks        │  │
           │  │  accumulate text + tool_calls      │  │
           │  │  append assistant turn to history  │  │
           │  │  if finish_reason == "stop" → exit │  │
           │  │  if tool_calls → execute all (‖)  │  │
           │  │  push role:"tool" results → loop   │  │
           │  └────────────────────────────────────┘  │
           │  if follow-up messages → continue outer  │
           │  else → break outer                      │
           └──────────────────────────────────────────┘
                   │
                   ▼
           stdout (streamed text + tool traces)
```

The key insight: the agent **is** this loop. LangChain, LangGraph, and pi.dev's `agent-core` package all export this same abstraction — they just package it differently. Pi's agent-core is under 750 lines.

## The 7 tools

The agent ships with exactly 7 tools — the same set pi.dev uses for coding tasks:

| Tool | What it does |
|------|-------------|
| `read_file` | Read file contents with optional line `offset` and `limit` |
| `write_file` | Create or overwrite a file |
| `edit_file` | Replace a specific string in a file (targeted, not full rewrite) |
| `bash` | Run any shell command; returns stdout + stderr + exit code |
| `grep` | Search for text patterns across files with line numbers |
| `find_files` | Find files by name pattern |
| `list_dir` | List directory contents with file sizes |

Tools run in parallel when the LLM requests multiple at once. Tool errors are returned as strings — never raised as Python exceptions — so the model can reason about what went wrong.

## Provider abstraction

Instead of pi.dev's hand-rolled provider layer (40+ adapters), this project uses [LiteLLM](https://github.com/BerriAI/litellm). Swapping models is a one-string change:

```python
MODEL = "claude-sonnet-4-5"       # Anthropic
MODEL = "gemini/gemini-2.0-flash"  # Google
MODEL = "gpt-4o"                   # OpenAI
```

LiteLLM normalizes all provider responses to OpenAI's chunk format, so `agent.py` sees the same structure regardless of which model is running.

## Key design decisions

**stdout-only output.** Pi ships a full terminal UI (`packages/tui/`). This project streams text directly to stdout — one less dependency, easier to follow.

**Async throughout.** `provider.py`, `agent.py`, and all tool functions are `async`. This keeps the event loop free during streaming and enables true parallel tool execution with `asyncio.gather`.

**OpenAI message format.** Even when calling Anthropic models, the message history uses OpenAI's wire format. LiteLLM translates internally. This means `role: "tool"` for results (not `role: "user"`) and `tool_calls` arrays on assistant messages.

## Sub-pages

- [The Agent Loop](./the-agent-loop.md) — outer loop, inner loop phases A–E, `MAX_ITERATIONS`
- [Streaming & Event Accumulation](./streaming-and-events.md) — chunk structure, buffering by index, gotchas
- [Message Types](./message-types.md) — dataclasses, on-the-wire shapes, why arguments stay as strings
- [The Provider Layer](./provider-layer.md) — `stream_response()`, async rationale, LiteLLM internals
