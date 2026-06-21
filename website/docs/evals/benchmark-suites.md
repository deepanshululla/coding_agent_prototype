---
sidebar_position: 3
title: Benchmark Suites
description: The self-contained suites — smoke, toolcall, and the Aider polyglot benchmark — and how each is graded.
---

# Benchmark Suites

Three suites run without any heavy setup: `smoke` and `toolcall` are fully self-contained, and `polyglot` only needs a one-time sparse clone of a public benchmark repo. (The fourth suite, `swebench`, is heavier and gets [its own page](./swebench-lite.md).)

Run any of them through the same CLI:

```bash
uv run python -m evals.run <suite> [--model M] [--limit N] [--out runs.jsonl]
```

Suites are registered as **lazy loaders** in `evals/run.py`, so naming `polyglot` clones its data only when actually requested — running `smoke` never touches the network.

## The `smoke` suite

Three toy tasks (`evals/suites/smoke.py`), one per dimension, designed to be fast and cheap enough to run on every change:

| Task | Tests | Grader |
|---|---|---|
| `add-function` | Write a function that passes hidden tests | `pytest_grader` |
| `fix-bug` | Edit buggy code so seeded tests pass | `pytest_grader` |
| `count-lines` | Drive the shell to produce an answer | `command_grader` |

```bash
uv run python -m evals.run smoke
```

Use this as a regression gate: if the smoke suite stops passing, something in the agent loop broke.

## The `toolcall` suite

Where `smoke` measures whether the agent gets the right *answer*, `toolcall` (`evals/suites/toolcall.py`) stresses the **tool-calling itself**. Each task is shaped so a model that can't reliably pick the right tool and pass it valid arguments will fail, no matter how good its prose is:

| Task | Tool path |
|---|---|
| `read-secret` | `read_file` — pull a value out of a seed file |
| `grep-locate` | `grep`/`find`/`bash` — find which file holds a token |
| `edit-version` | `edit_file` — change one constant in place |
| `write-config` | `write_file` — create a file with exact contents |
| `bash-count` | `bash` — count lines via the shell |
| `read-edit-chain` | multi-step — read a number, double it, write it back |

All are self-contained and graded by end-state. This suite is most useful run **across models** — the pass rate plus the per-run [`ToolStats`](./the-harness.md#what-a-result-records) rank models on exactly the dimension that varies most between them. See [Comparing models](./comparing-models.md).

```bash
uv run python -m evals.run toolcall
```

## The `polyglot` suite

The [Aider polyglot benchmark](https://github.com/Aider-AI/polyglot-benchmark) — Exercism exercises that give a problem statement, a stub to fill in, and a hidden test suite. It's the recommended first *real* benchmark: a genuine multi-file edit-then-test loop, but self-contained per exercise (no per-task repo setup).

```bash
uv run python -m evals.run polyglot --limit 10 --out runs.jsonl
```

On first run, `ensure_polyglot_repo()` sparse-clones the benchmark into `evals/.cache/` (gitignored). `load_polyglot()` then walks `<lang>/exercises/practice/*` and builds one `Task` per exercise:

- the instructions become the prompt,
- the stub and hidden test are seeded into the workdir,
- the `.meta/example.py` reference solution is **deliberately withheld** from the agent,
- grading runs pytest.

:::note Language support
Only **Python** is wired up so far. Other languages slot in by adding an entry to the `_LANGUAGES` spec dict in `evals/suites/polyglot.py` with that language's test command (via `command_grader`) and file conventions — gated on having that toolchain installed in the run environment.
:::

## Related pages

- [The harness](./the-harness.md) — how a `Task` and grader fit together
- [SWE-bench Lite](./swebench-lite.md) — the heavier, real-world suite
- [Comparing models](./comparing-models.md) — running a suite across many models
