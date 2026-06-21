# Eval harness for the coding agent

Status: in progress (Phases 1–3 done; Phase 4 is real SWE-bench Docker grading)

## Goal

Measure the agent on coding benchmarks. Phase 1 (done) is an in-repo harness +
a smoke suite covering three dimensions; Phase 2+ plugs real public benchmarks
into the same harness.

Dimensions we chose to measure (deliberately *not* full SWE-bench real-issue
fixing yet):
1. **Code-writing correctness** — write/edit code that passes hidden tests.
2. **Agent-loop / tool use** — drive bash/grep/find to complete a task.
3. **Cheap regression gate** — fast, deterministic smoke pass on every change.

## What exists (Phase 1 — done)

Top-level `evals/` package (added `"."` to `pyproject` `pythonpath` so it
imports in tests; `evals/__init__.py` prepends `src/` so `from sdk import …`
works under `python -m`):

| File | Role |
|------|------|
| `evals/graders.py` | Pure `(workdir) -> GradeResult` graders: `pytest_grader`, `command_grader`, `file_contains`. |
| `evals/harness.py` | `Task` + `EvalResult` dataclasses; async `run_task()` — temp workdir, seed files, `chdir`, run agent via `sdk.run_agent_collecting`, sum `turn_end` token usage, grade, restore cwd. Agent run is caught so one bad task never aborts a suite. |
| `evals/suites/smoke.py` | `SMOKE_SUITE`: `add-function` (pytest), `fix-bug` (edit + pytest), `count-lines` (bash). |
| `evals/run.py` | CLI: `python -m evals.run <suite> [--model M]`; prints table, exits non-zero on any fail (CI gate). |

Tests (all green, 20): `tests/test_evals_graders.py`, `test_evals_harness.py`
(fake agent runner — no API cost), `test_evals_run.py`.

Verified end-to-end: `uv run python -m evals.run smoke` → 3/3 pass, ~1.7k tokens.

Key design fact: the agent's tools are **cwd-relative** (`main.py` does
`os.chdir`), so the harness isolates each task by `chdir`-ing into a
`TemporaryDirectory`. Token usage rides on `turn_end` events as
`{"usage": {"total_tokens": N}}`.

## Phase 2 — first real benchmark (done)

Aider polyglot wired in as the first real benchmark, plus the two harness
extensions a real (large) suite needs.

| File | Role |
|------|------|
| `evals/suites/polyglot.py` | `ensure_polyglot_repo()` sparse-clones the benchmark into `evals/.cache/` (gitignored); `load_polyglot()` walks `<lang>/exercises/practice/*` and builds one `Task` per exercise (instructions → prompt, stub + test as seed files, `.meta/example.py` reference deliberately withheld, `pytest_grader`). **Python only**; other languages slot in via the `_LANGUAGES` spec dict. |
| `evals/results.py` | `append_run()` — JSONL, one record per task per run, tagged with model + ISO timestamp. Appends (history accumulates). |
| `evals/run.py` | `polyglot` suite registered as a lazy thunk (no clone unless requested); `--limit N`, `--out FILE`, `--verbose` flags; transcript silenced by default (`_silence_transcript` nulls `renderer.emit`; event collection / token accounting unaffected). |

Tests (all green): `test_evals_polyglot.py` (fake exercise dir — no network),
`test_evals_results.py`. Full suite 425 passed.

Verified end-to-end: `uv run python -m evals.run polyglot --limit 2 --out runs.jsonl`
→ 2/2 pass (affine-cipher, beer-song), results persisted.

## Phase 3 — SWE-bench, tool-calling, model comparison, docs (done)

`Task.setup` hook + `GradeResult.artifact`/`EvalResult.artifact` (harness),
SWE-bench Lite slice, a tool-calling suite + `ToolStats`, multi-model comparison
with Ollama discovery, and full Docusaurus docs.

| File | Role |
|------|------|
| `evals/harness.py` | `Task.setup: Callable[[Path],None]\|None` (runs in workdir before agent, e.g. repo clone); `GradeResult.artifact`/`EvalResult.artifact` (machine output, e.g. a diff); `ToolStats` + `tool_stats(events)` (calls/errors/unknown tool names); `run_task` lifts the permission policy to allow-all for the throwaway workdir and restores it after. |
| `evals/suites/swebench.py` | SWE-bench Lite as the *prediction* half: fetch instances via HF datasets-server (urllib, no `datasets` dep); `clone_setup` (git fetch-by-sha @ base_commit); `capture_patch_grader` (git add -A + diff → artifact); `load_swebench`; `write_predictions` (SWE-bench JSONL). Grading delegated to the official Docker harness. |
| `evals/suites/toolcall.py` | Tasks solvable only by correct tool use; ranks models on tool-calling via ToolStats. |
| `evals/models.py` | Ollama `/api/tags` discovery → `ollama_chat/` ids (the prefix that supports tool calling). |
| `evals/run.py` | `swebench`/`toolcall` suites; `--predictions`, `--models`, `--ollama-all`; `format_comparison` (rank by pass rate + surface tool-error / unknown columns). |
| `evals/results.py` | JSONL now also records `tool_calls`/`tool_errors`/`tool_unknown`. |
| `website/docs/evals/` | 5 Docusaurus pages (overview, the-harness, benchmark-suites, swebench-lite, comparing-models); site builds clean. |

Tests: `test_evals_swebench.py`, `test_evals_toolcall.py` (+ harness/results
additions). Full suite **444 passed**. Verified end-to-end: cloned `pallets/flask`
@ base commit, agent correctly diagnosed flask-4045 (dotted blueprint names),
produced a patch, wrote valid predictions JSONL.

## Phase 4 — SWE-bench Docker grading (done)

Closes the SWE-bench loop: predictions → official harness → true *resolved* rate.

| File | Role |
|------|------|
| `evals/swebench_grade.py` | `parse_report` (pure, reads swebench's report JSON), `find_report` (globs `<model>.<run_id>.json`), `grade_predictions` (subprocess `python -m swebench.harness.run_evaluation`), `GradeReport{submitted,resolved,…,resolved_rate}`, `format_grade`, `main()` CLI. |
| `evals/run.py` | `--grade` flag — runs the agent on the slice, writes predictions, grades via Docker, prints resolved rate; exits 0 iff all submitted resolved (real correctness gate). |
| `pyproject.toml` | `swebench>=3.0.0` in a new `evals` dependency group (heavy/Docker — `uv sync --group evals`). |
| `website/docs/evals/swebench-lite.md` | Documents `--grade` and the standalone `evals.swebench_grade` module. |

**Verified end-to-end through Docker** (swebench 4.1.0):
- Agent's flask-4045 prediction → built image, ran tests (4m43s), report parsed →
  **0/1 resolved**. The agent edited the right file so the "patch produced" proxy
  said PASS, but the real grade is unresolved — the exact gap Docker grading closes.
- Gold patch → **resolved** (✓=1, flask-4045 in `resolved_ids`, 1m12s on cached
  image). So `grade_predictions` reports BOTH outcomes correctly.

Bug found + fixed during verification: `grade_predictions` ran `.resolve()` on the
`gold`/`None` harness sentinels, mangling them into paths. Extracted pure
`_eval_command` (sentinel passthrough) + 2 TDD tests. `test_evals_swebench_grade.py`
now 9, all pure (no Docker).

Two ways to run:

    uv run python -m evals.run swebench --limit 5 --grade            # predict + grade
    uv run python -m evals.swebench_grade --predictions p.jsonl --run-id r  # grade only

Gotchas:
- Run grading with cwd OUTSIDE the repo (or set `workdir`) — the harness writes
  `logs/` and the report JSON into cwd. `--grade` / the standalone module handle
  this; ad-hoc scripts need `PYTHONPATH=<repo>` if cwd isn't the repo root.
- `--predictions_path gold` submits ALL 300 dataset instances, so a gold run with
  `--instance_ids` shows a 1/300 denominator — a gold-mode quirk, not the real
  `--grade` flow (which grades the agent's own N predictions).

## Phase 5 — HTML report (done)

Renders the accumulated JSONL run history into one self-contained HTML dashboard.

| File | Role |
|------|------|
| `evals/report_html.py` | Pure `load_records` / `summarize` / `render_html` (inline-CSS dashboard: summary cards, per-model leaderboard with pass-rate bars + tool stats, full detail table with PASS/FAIL badges; `html.escape` on detail). **Trend charts**: `_runs_over_time` + `_svg_line_chart` render inline-SVG pass-rate-over-time and tokens-over-time lines (one per model, no JS/CDN). `main()` CLI: `--in/--out/--title`. |
| `evals/results.py` | Extracted `result_to_record()` — single source of truth for the JSONL record schema, shared by `append_run` and the HTML path. |
| `evals/run.py` | HTML report **on by default** → `eval-report.html` (`_html_target`); `--html PATH` overrides, `--no-html` disables. Reflects the full `--out` history when given, else just this run. Works in single-model and `--compare` paths. (`eval-report.html` gitignored.) |
| `website/docs/evals/html-reports.md` | Docs page (charts + default behaviour). |

Tests `test_evals_report_html.py` (12, pure — incl. chart aggregation + SVG presence).
**Visually verified** via headless-Chrome screenshot: trend chart shows a model's
pass rate climbing 50%→100% across 3 dated runs; leaderboard bars + PASS/FAIL
badges render correctly. Full suite 484 passed.

## Roadmap (Phase 6+)

1. **More polyglot languages** — `_LANGUAGES` entries (go/rust/js…) via
   `command_grader`, gated on toolchains in the run env.
2. **HumanEval+ / EvalPlus** — cheapest single-function regression gate.
3. **SWE-bench Verified (full)** — once the Lite slice + Docker grade is proven.
4. **Charts in the HTML report** — pass-rate-over-time / token trend (the records
   carry `timestamp`); pairs with the `benchmark-chart` skill.

### Harness extensions still open
- Optional concurrency in `run_suite` (currently sequential).
- A small `analyze` step over the JSONL (pass-rate by model / over time) — pairs
  with the `benchmark-chart` skill for a results chart.
- SWE-bench predictions can include stray files the agent writes (e.g. a
  `SOLUTION.md`); harmless for grading but could be filtered to source-only.
