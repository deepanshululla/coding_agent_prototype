Status: done (2026-06-21) — both suites, harness metrics (iterations + answer
capture), answer-graders, STEPS columns, JSONL persistence, and Taskfile entries
shipped; 466 tests green; verified live across gpt-oss:20b + qwen3-coder:30b
(reasoning + coding comparison matrices). Stretch items below remain open.

# Reasoning and coding benchmarks as eval suites

## Goal

Add two model-comparison benchmarks to the eval harness — `reasoning` (multi-step
derivation, graded on the answer) and `coding` (standalone functions with hidden
tests, graded by pytest) — that plug into the existing `--models` / `--ollama-all`
comparison runner so any local Ollama model can be ranked on all three axes
(tool-calling, reasoning, coding) from one CLI.

## Background — what already exists (reuse, don't rebuild)

The tool-calling eval shipped (`evals/suites/toolcall.py`, ADR-0015 follow-on):
the harness runs a task in a sandboxed temp dir under an allow-all policy, sums
tokens, derives `ToolStats(calls, errors, unknown)` from the event stream, and
grades the workdir. `evals/run.py` already does multi-model fan-out
(`--models a,b,c`, `--ollama-all`), prints `format_comparison()`, and persists
per-task JSONL. `evals/models.py` discovers chat-capable Ollama models with the
`ollama_chat/` prefix. **All of this is reused unchanged** — the new suites only
add tasks + graders + a couple of metrics.

Coding is *partially* covered today: `smoke` has `add-function`/`fix-bug`,
`polyglot` runs real Exercism exercises (external sparse-clone, slower),
`swebench` needs Docker. The gap is a **fast, local, no-network coding suite**
for quick model comparison — the coding analogue of `toolcall`. Reasoning has no
coverage at all.

## Files changed

| File | Change |
|---|---|
| `evals/harness.py` | Add `iterations` to `EvalResult` (derive from events: count `turn_end`). Capture the run's **final assistant answer** (concat `text_delta`, or last assistant message from the returned `messages`) and expose it to graders so reasoning can be graded on the spoken answer, not a file. Add an `answer` kwarg path: `run_task` passes the answer text into answer-graders. |
| `evals/graders.py` | Add `exact_answer(expected, *, normalize=True)` — pass iff the run's final answer, normalized (strip, collapse ws, casefold, strip trailing punctuation), equals `expected`. Add `answer_contains(substr)`. Both operate on the captured answer text, not the workdir. Keep existing file/pytest/command graders untouched. |
| `evals/suites/reasoning.py` (new) | `REASONING_SUITE`: ~8 local, no-network tasks with deterministic answers — GSM8K-style arithmetic word problems, logic/constraint deduction, unit conversions, sequence/next-term, small planning ("in what order…"). Each graded by `exact_answer`. Prompts instruct: "reason step by step, then end with the final answer on its own line." |
| `evals/suites/coding.py` (new) | `CODING_SUITE`: ~8 local HumanEval-flavored tasks — a stub file + a hidden `test_*.py`; agent implements the function. Graded by `pytest_grader(test_file)`. Distinct from polyglot (external) and swebench (Docker). Designed to also run in **dual-model mode** (`AGENT_CODE_MODEL` set) to measure `write_code` delegation. |
| `evals/run.py` | Register `reasoning` and `coding` in `SUITES`. Add `iterations` (`STEPS`) column to `format_report` and `format_comparison`. No new flags — multi-model fan-out already works. |
| `evals/results.py` | Persist `iterations` (and keep the tool/answer fields) in the JSONL record. |
| `Taskfile.yml` | `eval:ollama:reasoning` and `eval:ollama:coding` (thin wrappers over `eval:ollama` with the suite arg), mirroring the existing `eval:ollama`. |
| `tests/test_evals_reasoning.py` (new) | `exact_answer` normalization (ws/case/punct), `answer_contains`, suite shape, and `run_task` answer capture + `iterations` metric (fake runner emitting `text_delta`/`turn_end`). |
| `tests/test_evals_coding.py` (new) | Coding suite shape; a fake-runner run_task that writes a passing impl → PASS, a wrong impl → FAIL via `pytest_grader`. |

## Order of operations

1. **Harness metrics first (no new suite yet).** Add `iterations` + final-answer
   capture to `EvalResult`/`run_task`; add `exact_answer`/`answer_contains`
   graders. Unit-test with fake runners. This is the smallest slice and unblocks
   both suites. (TDD: write the grader + capture tests, then implement.)
2. **`reasoning` suite + registration.** Add tasks, register in `SUITES`, add the
   `STEPS` column to the reports. Test suite shape. Run `--limit 2` against one
   fast model to smoke it live.
3. **`coding` suite + registration.** Add stub/hidden-test tasks graded by
   `pytest_grader`. Test pass/fail with fake runners. Smoke one task live.
4. **Reports + persistence + Taskfile.** Wire `iterations` into
   `format_comparison`, persist in JSONL, add the two `eval:ollama:*` tasks.
5. **Live comparison run** across the practical local models (tinyllama,
   gpt-oss:20b, qwen3-coder:30b) for both suites; record results. Optionally a
   dual-model coding pass (`AGENT_CODE_MODEL=ollama_chat/qwen3-coder:30b`) to
   quantify `write_code`'s effect.

## Verification

- [x] Tests: `tests/test_evals_reasoning.py`, `tests/test_evals_coding.py`, plus
      extended `tests/test_evals_harness.py` (iterations + answer capture). Full
      suite green (466).
- [x] CLI: `task eval:ollama:reasoning` and `task eval:ollama:coding` (and the
      `--models` form) print a comparison matrix — verified live.
- [x] Sample matrices (gpt-oss:20b vs qwen3-coder:30b): reasoning 4/4 vs 3/4;
      coding 1/3 vs 3/3 — the ranking flips by axis, which is the point.

## Design notes / decisions

- **Grade reasoning on the answer, not a file.** Forcing a math task to also
  `write_file` conflates reasoning with tool mechanics (and we saw weak models
  flail on tool calls). Capturing the final assistant text and grading that
  isolates the reasoning axis. Coding stays workdir/pytest-graded — that's the
  real artifact there.
- **Determinism over coverage for the local sets.** Curated answers are exact-
  checkable (numbers, single tokens, canonical strings). No LLM-judge in core —
  it adds cost and nondeterminism. (Stretch below.)
- **One comparison, three axes.** Because all suites share the runner, a future
  `eval:ollama:all` could run `toolcall` + `reasoning` + `coding` and emit a
  single per-model scorecard (pass-rate per axis, tool-error rate, steps, tokens).
- **`iterations` is a real signal.** Steps-to-solution separates a model that
  reasons in two turns from one that thrashes for ten — orthogonal to pass/fail.

## Stretch (out of scope for the first PR)

- **External breadth loaders**, mirroring `polyglot`: a GSM8K loader for
  `reasoning` (HF dataset) and HumanEval/MBPP for `coding`, behind on-demand
  fetch so the local curated sets stay the fast default.
- **LLM-judge grader** (`judge_grader(rubric)`) for open-ended reasoning answers,
  using a strong model via litellm — opt-in, never in the deterministic core.
- **Dual-model coding scorecard**: run `coding` single-model vs with
  `AGENT_CODE_MODEL` set and report the delta, quantifying the write_code
  delegation from ADR-0015.
- **`benchmark-chart` skill** to render the per-model scorecard as a PNG.
