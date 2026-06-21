---
sidebar_position: 4
title: SWE-bench Lite
description: Running the agent on real GitHub issues — the predict-then-grade split, the clone setup hook, and grading with the official Docker harness.
---

# SWE-bench Lite

[SWE-bench](https://www.swebench.com/) is the benchmark for real-world coding agents: each instance is an actual GitHub issue plus the repository at the commit where it was reported, and a solution is a patch that makes the project's hidden tests pass. **SWE-bench Lite** is the 300-instance subset most people iterate on.

```bash
uv run python -m evals.run swebench --limit 5 --predictions preds.jsonl
```

## Why grading is a separate step

SWE-bench's difficulty isn't just writing the patch — it's the **environment**. Each instance needs that project's exact dependencies, at a specific version, to run its tests. The official harness solves this by building a per-instance **Docker image**; reproducing that environment matrix in-process would be flaky and wrong.

So this suite does **not** try to grade correctness itself. It follows the standard two-phase split:

```
┌─────────────────────────┐        ┌──────────────────────────────┐
│  this harness           │        │  official swebench harness   │
│  (produce predictions)  │  ───▶  │  (grade, in Docker)          │
│                         │ preds  │                              │
│  clone repo @ commit    │ .jsonl │  build per-instance image    │
│  run agent → git diff   │        │  apply test patch, run tests │
└─────────────────────────┘        └──────────────────────────────┘
```

The harness **produces predictions** — it runs the agent against the real cloned repo and captures the resulting diff — and the canonical harness **grades** them. This is exactly how serious SWE-bench evaluation is done.

## How a SWE-bench task is built

`evals/suites/swebench.py` fetches instances dependency-free via the Hugging Face datasets-server JSON API (no `datasets` install needed), then builds one `Task` per instance using two harness features that exist for this purpose:

- **The `setup` hook** clones the repo at the base commit into the workdir. It uses fetch-by-sha so only the one commit is downloaded:

  ```python
  git init -q
  git remote add origin https://github.com/<repo>.git
  git fetch -q --depth 1 origin <base_commit>
  git checkout -q FETCH_HEAD
  ```

  This leaves the workdir as a git repo at exactly the state SWE-bench defines.

- **The grader captures the diff** as the candidate patch. It stages everything (so new files are included, as SWE-bench patches expect) and diffs against the base commit, returning the patch as the result's [`artifact`](./the-harness.md#what-a-result-records):

  ```python
  git add -A
  git diff --cached      # -> the model_patch
  ```

The problem statement becomes the prompt. The agent investigates the codebase, edits the source, and the diff of whatever it changed becomes the prediction.

:::caution The inline "PASS" is a proxy
For the `swebench` suite, the harness's own pass/fail means only **"a non-empty patch was produced"** — *not* that the issue is resolved. Real correctness comes from the Docker grading step below. The runner prints this reminder after a SWE-bench run.
:::

## Writing predictions

`--predictions PATH` writes a SWE-bench `predictions.jsonl` — one record per instance in the exact format the official harness consumes:

```json
{"instance_id": "pallets__flask-4045", "model_name_or_path": "claude-opus",
 "model_patch": "diff --git a/src/flask/blueprints.py ..."}
```

## Grading with the official harness

Grading needs the `swebench` package and a running Docker daemon. Because those are heavy, `swebench` lives in an optional dependency group rather than the default install:

```bash
uv sync --group evals     # installs swebench
```

### One command: predict + grade

`--grade` runs the agent on the slice, writes predictions, **and** grades them with the Docker harness in one go:

```bash
uv run python -m evals.run swebench --limit 5 --grade
```

It prints the true resolved rate and exits non-zero unless every submitted instance was resolved — so a graded run is a real correctness gate.

### Grading a predictions file you already have

Generate predictions now, grade later (or on a beefier machine) with the standalone module:

```bash
uv run python -m evals.run swebench --limit 5 --predictions preds.jsonl
uv run python -m evals.swebench_grade --predictions preds.jsonl --run-id my-run
```

Either path shells out to `swebench.harness.run_evaluation`, which builds the per-instance images, applies each instance's test patch, runs the `FAIL_TO_PASS` and `PASS_TO_PASS` tests, and writes a `<model>.<run-id>.json` report. `evals/swebench_grade.py` locates that report and parses it into a `GradeReport`:

```
Resolved 1/1 (100%) of submitted instances
  resolved:   pallets__flask-4045
```

:::tip Start with a slice
A full Lite run builds hundreds of multi-GB images and takes hours. Use `--limit` to run a handful of instances end-to-end first, and prefer instances from lighter repositories (e.g. `pallets/flask`, `psf/requests`) over the heavy ones (`django/django`, `astropy/astropy`) while you're wiring things up.
:::

## Related pages

- [The harness](./the-harness.md) — the `setup` hook and `artifact` field this suite relies on
- [Benchmark suites](./benchmark-suites.md) — the lighter, self-contained suites
- [Overview](./overview.md) — where SWE-bench sits among the dimensions
