---
sidebar_position: 5
title: Comparing Models
description: Run a suite across many models, rank them by pass rate, and surface the tool-calling quality that separates good agents from flailing ones.
---

# Comparing Models

The agent is provider-agnostic — the same loop runs against Claude, GPT, Gemini, or a local Ollama model. The eval runner can run a suite **once per model** and print a side-by-side comparison, so you can answer "which model should I actually use?" with numbers instead of vibes.

## Running a comparison

Two flags trigger the comparison path (either one runs the suite once per model):

```bash
# Explicit list
uv run python -m evals.run toolcall --models "claude-opus-4-8,gpt-4o,ollama_chat/qwen3-coder:30b"

# Every chat-capable model found in local Ollama
uv run python -m evals.run toolcall --ollama-all
```

A bare `--model` (or nothing) keeps the original single-run behaviour. Add `--out runs.jsonl` to persist every model's per-task results, each tagged with its model.

## The comparison report

`format_comparison()` ranks models by pass rate (best first) and surfaces the tool-calling signal alongside it:

```
MODEL                          PASS  TOOL_ERR  UNKNOWN    TOKENS
ollama_chat/qwen3-coder:30b    2/2        0%        0        420
ollama_chat/gpt-oss:20b        1/2       43%        2        510
```

The extra columns matter: a model can "pass" a task by **flailing** — making many tool calls, half of them erroring, some with hallucinated tool names — and that's a worse agent than one that solves cleanly, even at the same pass rate. The report makes that visible:

- **TOOL_ERR** — fraction of tool calls that came back an error (bad arguments, failed dispatch).
- **UNKNOWN** — calls to tools that don't exist, i.e. names the model invented.

These come from the per-run [`ToolStats`](./the-harness.md#what-a-result-records), derived purely from the event stream. The [`toolcall` suite](./benchmark-suites.md#the-toolcall-suite) is built specifically to make this dimension the thing that varies, so it's the natural suite to run across models.

## Ollama model discovery

`--ollama-all` calls `evals/models.py`, which queries the local Ollama server's `/api/tags` and maps the result to model ids the agent can use:

- Embedding models (matched by name markers like `embed`, `bge-m3`) are dropped — they can't chat or call tools.
- Each model gets the **`ollama_chat/`** prefix, not bare `ollama/`. This is deliberate: `ollama_chat/` routes through litellm to Ollama's `/api/chat` endpoint, the only one that supports tool calling. The bare `ollama/` prefix hits `/api/generate`, which silently ignores tools — useless for a tool-calling eval.

If the Ollama server is down or absent, discovery returns an empty list and the run degrades gracefully rather than crashing.

:::tip
This pairs well with the project's Ollama support — see the model-flag and `--ollama` shorthand in [Providers and Models](../getting-started/providers-and-models.md). Run `toolcall --ollama-all` after pulling a few models to see which local model is actually the best tool-caller on your machine.
:::

## Related pages

- [The harness](./the-harness.md) — where `ToolStats` comes from
- [Benchmark suites](./benchmark-suites.md) — the `toolcall` suite this is built for
- [Overview](./overview.md) — the dimensions a comparison spans
