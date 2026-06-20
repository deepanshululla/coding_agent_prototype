---
sidebar_position: 1
title: Overview & Roadmap
description: The tutorial roadmap — build a coding agent one concept per phase (each verified before and after), then a staged path of upgrades.
---

# Overview & Roadmap

An agent is a loop. Everything else — the provider, the tools, the prompt — exists to serve that loop. This tutorial builds the loop from scratch, **one concept per phase**, so each piece is understandable before the next arrives.

The **core build (Phases 1–9)** starts on the simplest possible model backend — shelling out to the `claude -p` CLI behind a small wrapper class, so you need no SDK and no API key to get going. **Phase 11** then swaps that backend for LiteLLM, at which point the code converges on the exact `src/` files in this repo. The **upgrades (Phases 10–18)** layer on everything else: a terminal UI, hardening, extensions, more interfaces, and the frontier.

## How each phase works

Two rules hold for every phase, and they are the point of the tutorial:

1. **Each phase builds on the last.** A phase starts from the working code the previous phase left behind (stated in its **Starting point** note) and adds exactly one concept. You never rewrite from scratch; you grow the same files.
2. **Each phase is verified before *and* after.** Every phase has a gate:
   - **Before** — you write the **Test it** test first and run it. It *fails*, naming the requirement that isn't met yet (red).
   - **After** — you add the **Build it** code and run the test again. It *passes* (green), and the **Run it** command lets you watch the new behavior with your own eyes.

   A phase isn't done until its test is green and its **Done when** acceptance (the roadmap table below) holds.

```bash
# Before: write the test, run it, watch it fail
uv run pytest tests/test_agent.py::test_new_thing -v   # FAILED  ← requirement not met yet

# After: add the code, run it again, watch it pass
uv run pytest tests/test_agent.py::test_new_thing -v   # PASSED  ← requirement met

# Run the whole suite at any checkpoint
uv run pytest -q
```

## Prerequisites

Python 3.11+, [`uv`](https://docs.astral.sh/uv/), and the [Claude CLI](https://docs.claude.com/en/docs/claude-code) (`claude`) **logged in** — the core build (Phases 1–9) shells out to it, so **no API key is required** to start. A provider API key (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, or `OPENAI_API_KEY`) only comes in at [Phase 11](./11-add-litellm.md), when you swap the backend for LiteLLM. See [Installation](../getting-started/installation.md) for full setup.

```bash
uv add python-dotenv     # core build
claude                   # one-time CLI login (or: claude setup-token)
# uv add litellm         # added in Phase 11
```

`pyproject.toml` sets `pythonpath = ["src"]` under `[tool.pytest.ini_options]`, so `from provider import ...` works in tests without path hacks.

:::tip
Each phase adds a small, runnable slice. If you get stuck, the final files in `src/` are the answer key — and `uv run pytest` already passes there (17 tests), which is what the tutorial converges on.
:::

## Phase roadmap

Each row is one phase: the concept it introduces, the **Done when** acceptance you verify, and the file(s) it grows.

| Phase | Concept introduced | Done when (verify) | File(s) |
|-------|--------------------|--------------------|---------|
| [1 — Talk to a Model](./01-talk-to-a-model.md) | A `ModelClient` wrapper class around `claude -p` — no SDK, no API key | A mocked CLI call returns the model's text; "say hi" gets a reply | `src/provider.py` |
| [2 — The Conversation Loop](./02-the-agent-loop.md) | The `messages` list as state; the while-loop skeleton; text-only stop | `run_agent` returns `[user, assistant]` and stops on a plain reply | `src/agent.py` |
| [3 — Streaming Responses](./03-streaming.md) | Rename to `stream_response`; stream `claude -p` as OpenAI-format chunks | Accumulated text equals the joined deltas; tokens print live | `src/provider.py`, `src/agent.py` |
| [4 — Your First Tool](./04-your-first-tool.md) | Tool schema + dispatch; results return as `role:"tool"` messages | The model calls `read_file`; its contents land in history; loop continues | `src/tools.py`, `src/types_.py`, `src/agent.py` |
| [5 — Streaming Tool Calls](./05-streaming-tool-calls.md) | Buffer partial-JSON arguments by `index`; `json.loads` after the stream | A tool call split across chunks parses correctly and executes | `src/agent.py` |
| [6 — A Toolbox](./06-a-toolbox.md) | All 7 tools behind a registry; the never-raise error contract | 7 tools registered; a missing file returns an error *string*, not a raise | `src/tools.py` |
| [7 — Parallel Tool Execution](./07-parallel-tools.md) | `asyncio.gather` over a turn's tools; `to_thread` for blocking I/O | Two tools in one turn run concurrently; both results return correctly | `src/agent.py` |
| [8 — System Prompt & CLI](./08-system-prompt-and-cli.md) | Dynamic prompt (cwd/date/tools); `MAX_ITERATIONS`; the CLI | Prompt contains cwd/date/tool list; `uv run main.py "…"` runs | `src/prompts.py`, `main.py`, `src/agent.py` |
| [9 — Testing the Agent](./09-testing-the-agent.md) | Deterministic tests via a scripted, mocked model | `uv run pytest -q` → **17 passed** with no network | `tests/` |
| [10 — Terminal UI](./10-terminal-ui/1-event-seam.md) | Layer a transcript / tool panel / input / status bar over the loop via an `emit()` seam (5 sub-layers) | `AGENT_UI=tui` renders the same events a stdout run prints | `src/agent.py` |
| [11 — Add LiteLLM](./11-add-litellm.md) | Swap the `claude -p` backend for LiteLLM; any provider via one model string | Loop tests still pass; swapping to `gpt-4o`/`gemini` is one string | `src/provider.py` |
| [12 — Harden It](./12-harden-it/1-security-model.md) | Safety in 5 layers: security model, command allowlist, permissions/modes, sandboxing, logging | Refuses unlisted commands; runs sandboxed; logs to stderr | _5 layers_ |
| [13 — Extend It](./13-extend-it/1-project-instructions.md) | Capabilities in 6 layers: AGENTS.md, templates/hooks, skills, Agent Skills, **MCP**, models/providers | Loads project instructions, skills, and MCP tools | _6 layers_ |
| [14 — Interface It](./14-interface-it/1-sdk.md) | Programmatic interfaces in 3 layers: SDK, RPC, JSON event stream | An SDK or HTTP caller drives the same loop | _3 layers_ |
| [15 — Steering](./15-steering.md) | Inject a follow-up into the outer loop without replaying the conversation | A steered follow-up continues from where it left off | `src/agent.py` |
| [16 — Context Compaction](./16-context-compaction.md) | Summarize old turns to reclaim context-window space | History past the threshold is compacted; the agent stays coherent | _design_ |
| [17 — Extended Thinking](./17-extended-thinking.md) | Give the model scratchpad reasoning off the visible context | The reasoning trace appears and shapes the answer | _design_ |
| [18 — Go Further & Close](./18-go-further.md) | BDD framework, architecture patterns, and the decision log | You can find every frontier feature, pattern, and decision | _docs_ |

## Architecture orientation

The completed agent has this structure:

```
User task
   │
   ▼
┌──────────────────────────────────────────┐
│              OUTER LOOP                   │  ← re-enters if follow-up messages arrive
│  ┌────────────────────────────────────┐  │
│  │           INNER LOOP               │  │  ← the core agent loop
│  │  stream response (Phase A)         │  │
│  │  append assistant turn (Phase B)   │  │
│  │  stop check (Phase C)              │  │
│  │  execute tools in parallel (D)     │  │
│  │  push tool results (Phase E)       │  │
│  └────────────────────────────────────┘  │
│  if follow-up messages → continue outer   │
│  else → break outer                       │
└──────────────────────────────────────────┘
```

**Phases 1–2** build the loop's outer shape (a `claude -p` wrapper + the text-only cycle). **Phases 3–5** add streaming and the tool-call protocol. **Phases 6–7** grow the toolbox and run tools in parallel. **Phase 8** completes the prompt and ships a CLI. **Phase 9** locks the behavior in with tests. Then the upgrades: **Phase 10** layers a terminal UI over the agent (five sub-layers, each building on the last), **Phase 11** swaps in LiteLLM (converging on the shipped `src/`), **Phases 12–14** harden, extend, and add programmatic interfaces, **Phases 15–17** add steering, compaction, and extended thinking, and **Phase 18** points to the architecture patterns and the decision log.

For a deeper read before or after the tutorial: [Architecture Overview](../architecture/overview.md).
