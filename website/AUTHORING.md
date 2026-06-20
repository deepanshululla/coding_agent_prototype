# Authoring guide (for doc contributors and agents)

Read this before writing any page under `docs/`. The goal is a coherent, technically
honest documentation set grounded in `PLAN.md`.

## Source of truth

- **`PLAN.md`** (repo root) is the canonical spec. Every code snippet, tool name, function
  signature, and design claim must match it. Do **not** invent APIs that aren't in the plan.
- The `src/*.py` files are scaffolded but **largely unimplemented**. When a page describes
  code, frame it as the planned design. Use a `:::note` to flag "planned, not yet
  implemented" where a reader might otherwise expect working code.
- This project mirrors [pi.dev](https://pi.dev) but is **stdout-only** (no TUI) and uses
  **LiteLLM** instead of a hand-rolled provider layer.

## Frontmatter (required on every page)

```markdown
---
sidebar_position: <int>   # order within the section
title: <Page Title>
description: <one sentence — used for search + social cards>
---
```

## House style

- **Audience:** an engineer learning how a coding agent works by building one. Explain the
  *why*, not just the *what*. Short paragraphs. Lead with the point.
- **Voice:** direct, concrete, calm. No hype, no "simply/just/obviously". Second person.
- **Admonitions:** use `:::note`, `:::tip`, `:::warning`, `:::info`, `:::danger` where they
  earn their place — gotchas, safety, side-notes. Don't overuse.
- **Code:** fenced blocks with a language (`python`, `bash`, `json`, `diff`). Keep Python
  snippets consistent with `PLAN.md` (async tools, OpenAI-style tool schemas, `role: "tool"`
  results, buffer-then-`json.loads` streaming). Prefer real, runnable snippets.
- **Tables** for comparisons and reference matrices.
- **Cross-links:** link related pages with **relative** paths ending in `.md`, e.g.
  `[the loop](../architecture/the-agent-loop.md)`. Link generously; readers arrive mid-tree.
- **Length:** enough to be genuinely useful — typically 150–500 lines for a substantive
  page, shorter for narrow reference pages. Don't pad.
- Start each page with an `# H1` matching the title, then a one–two sentence orientation.

## Key facts to keep consistent (from PLAN.md)

- 7 tools: `read_file`, `write_file`, `edit_file`, `bash`, `grep`, `find_files`, `list_dir`.
- Tools are `async def`; blocking I/O is wrapped in `await asyncio.to_thread(...)`.
- Tool errors are **returned as strings** with `is_error=True`, never raised.
- Tool calls execute **in parallel** via `asyncio.gather`.
- Provider layer is a single `stream_response()` over `litellm.acompletion(..., stream=True)`.
- Streaming is OpenAI-format chunks: buffer `tool_calls` fragments by `index`, `json.loads`
  the arguments **only after** the stream ends.
- Message history: assistant turns carry `tool_calls`; each tool result is its own
  `{"role": "tool", "tool_call_id": ..., "content": ...}` message.
- `MAX_ITERATIONS = 30`. Model selected by a single string (e.g. `"claude-sonnet-4-5"`).
- Modules: `src/agent.py`, `src/tools.py`, `src/prompts.py`, `src/provider.py`,
  `src/types_.py` (named `types_` to avoid shadowing stdlib `types`), `main.py`.
