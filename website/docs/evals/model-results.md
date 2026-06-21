---
sidebar_position: 6
title: Model Results
description: Measured results from running the suites across local Ollama models — tool-calling, reasoning, planning, and coding (HumanEval) — with the findings that only show up at larger N.
---

# Model Results

This page records **actual measured results** from running the harness across local
[Ollama](https://ollama.com) models. The mechanics live on the other pages
([the harness](./the-harness.md), [suites](./benchmark-suites.md),
[comparing models](./comparing-models.md)); this is the data those tools produced.

:::note Reproducibility & caveats
These are **illustrative local runs on one machine** (Apple Silicon, models served
through `ollama_chat/`). Absolute numbers depend on hardware, quant, and sample
size — some slices are small (`--limit`). Treat the *rankings and patterns* as the
signal, not the exact percentages. Re-run any of this with
`task eval:ollama:<suite>` and your own `--limit`.
:::

## Tool-calling, reasoning, planning (local suites)

The fast, self-contained suites across the practical local models:

| Model | Tool-calling | Reasoning | Planning | Coding (local) |
|---|:--:|:--:|:--:|:--:|
| **gemma4:8b** | 6/6 · 0 err | 4/4 | 5/5 | 3/3 |
| qwen3-coder:30b | 5/6 · 0 err | 3/4 | 5/5 | 3/3 |
| gpt-oss:20b | 6/6 · **4 err** | 4/4 | 5/5 | **1/3** |
| gemma3:27b | — *(tool-less)* | 4/4 | 5/5 | — |
| tinyllama | 0/6 *(tool-less)* | — | — | — |
| gpt-oss:120b | *unrunnable here* | — | — | — |

Key reads:

- **Tool-calling quality ≠ pass rate.** gpt-oss:20b *passes* the toolcall suite but
  flails — extra calls and bad-argument errors (the `ERR` column). qwen3-coder and
  gemma4 drive tools cleanly (0 errors). This is exactly the signal the
  [ToolStats](./the-harness.md) columns expose.
- **The small local coding suite is not discriminating.** gemma4:8b and
  qwen3-coder both score 3/3 — it takes a standard benchmark to separate them
  (below).
- **Tool-less models** (`gemma3`, `tinyllama`) reject any request carrying a
  `tools` array. The provider retries once **without** tools, so they can still run
  the answer-graded axes (reasoning/planning) but score ~0 on tool/coding suites.
- **gpt-oss:120b does not run on this hardware** — the 71 GB model spills to CPU,
  hangs for minutes, and OOM-crashes the Ollama server. The harness records it as a
  failed task rather than crashing the run.

## Coding at larger N — HumanEval

The local coding suite called several models "perfect" (3/3). The standard
[HumanEval](https://github.com/openai/human-eval) slice (`--limit 5`,
HumanEval/0–4) ranks them cleanly:

| Model | Score | Tool errors | Wall time |
|---|:--:|:--:|:--:|
| **gemma4:31b** | **5/5 (100%)** | 0 | ~28 min |
| gemma4:8b | 3/5 (60%) | 0 | ~7 min |
| gpt-oss:20b | 1/5 (20%) | 10 | ~2 min |

Per task:

```
task          gpt-oss:20b   gemma4:8b   gemma4:31b
HumanEval/0   FAIL          FAIL        PASS    ← has_close_elements (threshold)
HumanEval/1   FAIL          PASS        PASS
HumanEval/2   PASS          PASS        PASS    ← truncate_number
HumanEval/3   FAIL          FAIL        PASS    ← below_zero (empty-list edge)
HumanEval/4   FAIL          PASS        PASS
```

What the bigger benchmark reveals that the small one couldn't:

- **Size buys edge-case robustness.** gemma4 **8b → 31b: 60% → 100%**. The 31b fixed
  *exactly* the two cases the 8b missed — a numerical-threshold problem and an
  empty-list edge case.
- **gpt-oss:20b is the weakest coder (20%)** despite being the largest of the small
  models, and it's the only one making tool errors (10). Fast but wrong.
- **Accuracy costs latency.** gemma4:31b's 100% took ~4× the 8b's wall time (~28 min
  vs ~7 min for 5 problems). For interactive use the 8b is far more practical; for
  max correctness offline, the 31b earns its keep.

## Takeaways

- For a **local agent that uses tools**, `gemma4:8b` is the standout small model —
  clean tool-calling, solid reasoning/planning, and the best coding-per-size.
- `qwen3-coder:30b` is a strong, clean coder; `gpt-oss:20b` reasons and plans fine
  but is a poor, error-prone coder.
- Reach for `gemma4:31b` when you want maximum coding correctness and can absorb the
  latency.
- Always confirm a model actually **supports tools** before trusting an agent run —
  and prefer the `ollama_chat/` prefix (see [Comparing Models](./comparing-models.md)).

## Reproduce

```bash
# Four axes across every local model (use --limit to keep it quick)
task eval:ollama -- --limit 6           # tool-calling
task eval:ollama:reasoning -- --limit 5
task eval:ollama:planning  -- --limit 5
task eval:ollama:coding    -- --limit 5

# Standard datasets (large N, fetched on demand)
task eval:ollama:gsm8k     -- --limit 30
task eval:ollama:humaneval -- --limit 5

# Persist history + open the HTML report
uv run python -m evals.run humaneval \
  --models "ollama_chat/gemma4:31b,ollama_chat/gemma4:latest,ollama_chat/gpt-oss:20b" \
  --limit 5 --out evals/runs.jsonl --html eval-report.html
```

Persisted run history lives in `evals/runs.jsonl` (gitignored); the
[HTML report](./html-reports.md) renders the leaderboard and trend charts from it.
