---
sidebar_position: 1
title: Overview
description: Why the agent ships with an eval harness, the four dimensions it measures, and the suites built on top of it.
---

# Overview

A coding agent is only as good as what it can actually *do* — and the only way to know that is to run it against tasks with a right answer and count how often it gets there. This project ships a small **eval harness** for exactly that: it stands up an isolated workspace, runs the agent on a task, and grades the result. On top of the harness sit several **suites**, from a fast smoke gate to real-world GitHub issues.

The whole thing lives in the top-level `evals/` package, parallel to `tests/`. It drives the agent through the same in-process [SDK seam](../programmatic-usage/sdk.md) the rest of the project uses, so an eval run exercises the real agent loop — model, tools, and all.

## What it measures

Different suites probe different dimensions of agent quality:

| Dimension | Question | Suite |
|---|---|---|
| **Code-writing correctness** | Can it write/edit code that passes hidden tests? | `polyglot`, `smoke` |
| **Tool use** | Does it pick the right tool and pass valid arguments? | `toolcall` |
| **Real-world fixing** | Can it resolve an actual GitHub issue in a real repo? | `swebench` |
| **Cheap regression gate** | Did the last change break basic behaviour? | `smoke` |

Every run also records **cost** (token usage), **latency**, and **tool-calling quality** (how many tool calls, how many errored, how many were hallucinated names) — so a model that "passes" by flailing is visibly worse than one that solves cleanly. See [Comparing models](./comparing-models.md).

## The built-in suites

| Suite | What it is | Self-contained? |
|---|---|---|
| [`smoke`](./benchmark-suites.md#the-smoke-suite) | 3 toy tasks across the dimensions — a fast gate | Yes |
| [`toolcall`](./benchmark-suites.md#the-toolcall-suite) | Tasks solvable only by driving tools correctly | Yes |
| [`polyglot`](./benchmark-suites.md#the-polyglot-suite) | The Aider polyglot benchmark (Exercism exercises) | Clones a repo |
| [`swebench`](./swebench-lite.md) | A SWE-bench Lite slice — real GitHub issues | Clones repos + Docker to grade |

## Quick start

```bash
# Fast gate — 3 toy tasks, uses your configured model
uv run python -m evals.run smoke

# A slice of the Aider polyglot benchmark, persisting results
uv run python -m evals.run polyglot --limit 10 --out runs.jsonl

# Real GitHub issues → SWE-bench predictions for the official grader
uv run python -m evals.run swebench --limit 5 --predictions preds.jsonl

# Compare local Ollama models on tool-calling
uv run python -m evals.run toolcall --ollama-all
```

The runner exits non-zero if any task fails, so it doubles as a CI gate.

## Related pages

- [The harness](./the-harness.md) — `Task`, graders, `run_task`, and what a result records
- [Benchmark suites](./benchmark-suites.md) — the self-contained suites and how to add your own
- [SWE-bench Lite](./swebench-lite.md) — running real issues and grading with the official harness
- [Comparing models](./comparing-models.md) — multi-model runs and the tool-calling signal
- [HTML reports](./html-reports.md) — render the full run history into a self-contained dashboard
