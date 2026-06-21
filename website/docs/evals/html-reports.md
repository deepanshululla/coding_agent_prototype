---
sidebar_position: 6
title: HTML Reports
description: Turn the accumulated JSONL run history into a single self-contained HTML dashboard — overall summary, per-model leaderboard, and a full detail table.
---

# HTML Reports

The harness appends every run to a JSONL file (`--out`, see [The harness](./the-harness.md#persisting-results)). `evals/report_html.py` turns that accumulated history into **one self-contained HTML page** — no external assets (the charts are inline SVG, no JS or CDN), so it opens anywhere and is easy to attach to a PR or CI artifact.

## Generating a report

### It's on by default

Every `evals.run` writes the report automatically — you don't need a flag. By default it lands at **`eval-report.html`** in the working directory:

```bash
uv run python -m evals.run toolcall --out runs.jsonl   # also writes eval-report.html
```

Override the path with `--html PATH`, or turn it off with `--no-html`. When `--out` is given, the report reflects the **full JSONL history** (every prior run plus this one); without `--out`, it reflects just this run:

```bash
uv run python -m evals.run toolcall --ollama-all --out runs.jsonl --html report.html
uv run python -m evals.run smoke --no-html            # skip the report
```

### From the accumulated history, standalone

Point the standalone tool at a runs file to render **everything** the harness has recorded:

```bash
uv run python -m evals.report_html --in runs.jsonl --out report.html --title "Coding Agent Evals"
```

## What's in it

The page is built from pure functions (`load_records`, `summarize`, `render_html`), each a deterministic function of the record list:

- **Summary cards** — overall pass rate, passed/total, number of runs, models, total tokens.
- **Trend charts** — inline-SVG line charts of **pass rate over time** and **tokens per run over time**, one coloured line per model. A "run" is grouped by timestamp, so re-running a suite day over day plots a trajectory — you can see a model (or a prompt change) improving or regressing across commits. No data, no charts; no JS, no external requests.
- **Model leaderboard** — one row per model, sorted best-pass-rate-first, with a pass-rate bar plus tool calls / errors / hallucinated-tool-name counts and tokens. The same tool-calling quality signal as the [comparison report](./comparing-models.md), persisted.
- **Detail table** — every recorded result, newest first: when, model, task, a colour-coded PASS/FAIL badge, iterations, tool stats, tokens, time, and the first line of the grader's detail.

The trend charts are most useful with `--out` pointed at a long-lived runs file, so history accumulates across days and commits.

A "run" is a distinct `(timestamp, model)` pair, so re-running a suite across models and over time accumulates into a single comparable view.

:::note Untrusted detail is escaped
Grader `detail` text (e.g. a failing-test traceback line) is HTML-escaped before it reaches the page, so a stray `<script>` in output can't execute when you open the report.
:::

## Related pages

- [The harness](./the-harness.md#persisting-results) — the JSONL schema the report reads
- [Comparing models](./comparing-models.md) — the live (terminal) version of the leaderboard
- [Benchmark suites](./benchmark-suites.md) — the suites whose results you're charting
