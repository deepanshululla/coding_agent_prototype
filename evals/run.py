"""CLI runner: drive a suite of eval tasks and report pass/fail + token cost.

    uv run python -m evals.run smoke                    # configured/default model
    uv run python -m evals.run smoke --model gpt-4o     # override the model
    uv run python -m evals.run polyglot --limit 10      # first 10 polyglot tasks
    uv run python -m evals.run polyglot --out runs.jsonl  # persist results

Suites are registered as lazy loaders so naming one (e.g. ``polyglot``) only
clones its data when actually requested. Exits non-zero when any task fails, so
the runner doubles as a CI gate.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from evals.harness import EvalResult, Task, run_task
from evals.results import append_run


def _load_smoke() -> list[Task]:
    from evals.suites.smoke import SMOKE_SUITE

    return SMOKE_SUITE


def _load_toolcall() -> list[Task]:
    from evals.suites.toolcall import TOOLCALL_SUITE

    return TOOLCALL_SUITE


def _load_reasoning() -> list[Task]:
    from evals.suites.reasoning import REASONING_SUITE

    return REASONING_SUITE


def _load_coding() -> list[Task]:
    from evals.suites.coding import CODING_SUITE

    return CODING_SUITE


def _load_planning() -> list[Task]:
    from evals.suites.planning import PLANNING_SUITE

    return PLANNING_SUITE


def _load_gsm8k() -> list[Task]:
    from evals.suites.gsm8k import load_gsm8k

    return load_gsm8k()


def _load_humaneval() -> list[Task]:
    from evals.suites.humaneval import load_humaneval

    return load_humaneval()


def _load_polyglot() -> list[Task]:
    from evals.suites.polyglot import ensure_polyglot_repo, load_polyglot

    return load_polyglot(ensure_polyglot_repo())


def _load_swebench() -> list[Task]:
    from evals.suites.swebench import fetch_instances, load_swebench

    # A slice by default; widen with --limit (the harness slices the list).
    return load_swebench(fetch_instances(limit=100))


#: Registry of named suites -> a thunk that builds the task list on demand.
#: Local suites (fast, offline) and large standard datasets fetched on demand
#: (gsm8k → reasoning, humaneval → coding) — use --limit to subsample either.
SUITES: dict[str, Callable[[], list[Task]]] = {
    "smoke": _load_smoke,
    "toolcall": _load_toolcall,
    "reasoning": _load_reasoning,
    "planning": _load_planning,
    "coding": _load_coding,
    "gsm8k": _load_gsm8k,
    "humaneval": _load_humaneval,
    "polyglot": _load_polyglot,
    "swebench": _load_swebench,
}


def get_suite(name: str) -> list[Task]:
    """Build a suite by name, raising a helpful KeyError when unknown."""
    try:
        loader = SUITES[name]
    except KeyError:
        available = ", ".join(sorted(SUITES))
        raise KeyError(f"unknown suite {name!r}; available: {available}") from None
    return loader()


def format_report(results: list[EvalResult]) -> str:
    """Render results as a fixed-width table with pass-rate, tool-call, and token
    summaries. The CALLS/ERR/UNK columns expose tool-calling quality per task:
    how many tools were invoked, how many failed, and how many were hallucinated
    (non-existent) tool names."""
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    width = max((len(r.task_id) for r in results), default=4)

    lines = [
        f"{'TASK'.ljust(width)}  RESULT  {'STEPS':>5} {'CALLS':>5} {'ERR':>4} {'UNK':>4}  "
        f"{'TOKENS':>8}  {'TIME':>6}"
    ]
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        s = r.tool_stats
        lines.append(
            f"{r.task_id.ljust(width)}  {mark}    {r.iterations:>5} "
            f"{s.calls:>5} {s.errors:>4} {s.unknown:>4}  "
            f"{r.total_tokens:>8}  {r.duration_s:>5.1f}s"
        )

    total_tokens = sum(r.total_tokens for r in results)
    total_calls = sum(r.tool_stats.calls for r in results)
    total_errors = sum(r.tool_stats.errors for r in results)
    lines.append("")
    lines.append(
        f"{passed}/{total} passed   {total_calls} tool calls "
        f"({total_errors} errored)   {total_tokens} tokens total"
    )
    return "\n".join(lines)


def _short_model(model: str) -> str:
    """Drop the ``ollama_chat/`` / ``ollama/`` prefix for a compact column."""
    return model.removeprefix("ollama_chat/").removeprefix("ollama/")


def format_comparison(by_model: dict[str, list[EvalResult]]) -> str:
    """Render a model-vs-model matrix, best pass-rate first.

    One row per model: pass count, total tool calls, errored calls, hallucinated
    (unknown) tool names, tokens, and wall time. This is the headline output of a
    multi-model tool-calling eval — it ranks local models on whether they drive
    tools cleanly, not just whether they eventually stumble to the answer.
    """
    rows = []
    for model, results in by_model.items():
        passed = sum(1 for r in results if r.passed)
        total = len(results)
        rows.append(
            {
                "model": _short_model(model),
                "passed": passed,
                "total": total,
                "rate": passed / total if total else 0.0,
                "steps": sum(r.iterations for r in results),
                "calls": sum(r.tool_stats.calls for r in results),
                "errors": sum(r.tool_stats.errors for r in results),
                "unknown": sum(r.tool_stats.unknown for r in results),
                "tokens": sum(r.total_tokens for r in results),
                "time": sum(r.duration_s for r in results),
            }
        )
    # Best pass-rate first; break ties by fewer errored tool calls.
    rows.sort(key=lambda r: (-r["rate"], r["errors"]))

    width = max((len(str(r["model"])) for r in rows), default=5)
    lines = [
        f"{'MODEL'.ljust(width)}  {'PASS':>5}  {'STEPS':>5} {'CALLS':>5} {'ERR':>4} {'UNK':>4}  "
        f"{'TOKENS':>8}  {'TIME':>6}"
    ]
    for r in rows:
        lines.append(
            f"{str(r['model']).ljust(width)}  {r['passed']:>2}/{r['total']:<2}  "
            f"{r['steps']:>5} {r['calls']:>5} {r['errors']:>4} {r['unknown']:>4}  "
            f"{r['tokens']:>8}  {r['time']:>5.1f}s"
        )
    return "\n".join(lines)


def _silence_transcript() -> None:
    """Swap the renderer's emitter for a no-op so agent transcript stays off stdout.

    The SDK forwards collected events to ``renderer.emit`` at call time, so
    nulling it here keeps large suites readable while event collection (and thus
    token accounting) is unaffected. This is a CLI-layer I/O concern; the harness
    itself stays renderer-agnostic.
    """
    import renderer

    renderer.emit = lambda event: None


async def run_suite(tasks: list[Task], model: str | None = None) -> list[EvalResult]:
    """Run every task in order, printing each verdict as it completes."""
    results: list[EvalResult] = []
    for i, task in enumerate(tasks, 1):
        result = await run_task(task, model=model)
        mark = "PASS" if result.passed else "FAIL"
        print(
            f"  [{i}/{len(tasks)}] [{mark}] {task.id} "
            f"({result.total_tokens} tok, {result.duration_s:.1f}s)"
        )
        if not result.passed and result.detail:
            print(f"         {result.detail.splitlines()[0]}")
        results.append(result)
    return results


def _resolve_models(args) -> list[str] | None:
    """Resolve the comparison model list, or ``None`` for a single-model run.

    ``--ollama-all`` discovers chat-capable models from local Ollama; ``--models``
    is an explicit comma list. Neither flag → ``None`` (single run via ``--model``).
    """
    if args.ollama_all:
        from evals.models import discover_chat_models

        return discover_chat_models()
    if args.models:
        return [m.strip() for m in args.models.split(",") if m.strip()]
    return None


#: Where the HTML report goes when --html isn't given (it's on by default).
DEFAULT_HTML = "eval-report.html"


def _html_target(args) -> str | None:
    """Resolve the HTML report path: --html wins, else the default, unless --no-html."""
    if args.no_html:
        return None
    return args.html or DEFAULT_HTML


def _emit_html(html_path: str, out_path: str | None, records: list[dict]) -> None:
    """Write an HTML report. Prefers the full JSONL history (``--out``) so the page
    shows ALL of the harness's results; otherwise reports just this run's records."""
    from evals.report_html import load_records, render_html

    if out_path:
        records = load_records(Path(out_path))
    Path(html_path).write_text(render_html(records))
    print(f"\nHTML report written to {html_path} ({len(records)} results)")


def _records_for(results: list[EvalResult], model: str | None) -> list[dict]:
    """Flatten this run's results into JSONL-shaped records (for HTML without --out)."""
    from evals.results import result_to_record

    ts = datetime.now().isoformat()
    return [result_to_record(r, model=model, timestamp=ts) for r in results]


def _run_comparison(args, tasks: list[Task], models: list[str]) -> int:
    """Run the suite once per model and print a comparison matrix.

    Returns 0 iff every model passed every task — so a comparison run is still a
    usable CI gate. Each model's per-task results are persisted when ``--out`` is
    set, tagged with that model.
    """
    if not models:
        print("No models to compare (none given / none discovered).", file=sys.stderr)
        return 2

    by_model: dict[str, list[EvalResult]] = {}
    for model in models:
        print(f"\n=== {model} — suite '{args.suite}' ({len(tasks)} tasks) ===")
        results = asyncio.run(run_suite(tasks, model=model))
        by_model[model] = results
        if args.out:
            append_run(args.out, results, model=model, timestamp=datetime.now().isoformat())

    print("\n" + format_comparison(by_model))
    if args.out:
        print(f"\nResults appended to {args.out}")
    html_target = _html_target(args)
    if html_target:
        flat = [rec for m, rs in by_model.items() for rec in _records_for(rs, m)]
        _emit_html(html_target, args.out, flat)
    return 0 if all(r.passed for rs in by_model.values() for r in rs) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a coding-agent eval suite.")
    parser.add_argument("suite", help=f"suite name ({', '.join(sorted(SUITES))})")
    parser.add_argument("--model", default=None, help="override the agent model")
    parser.add_argument(
        "--models",
        default=None,
        help="comma-separated models to compare (runs the suite once per model)",
    )
    parser.add_argument(
        "--ollama-all",
        action="store_true",
        help="compare across every chat-capable model discovered in local Ollama",
    )
    parser.add_argument("--limit", type=int, default=None, help="run only the first N tasks")
    parser.add_argument("--out", default=None, help="append results as JSONL to this file")
    parser.add_argument(
        "--html",
        default=None,
        help=f"HTML report path (default: {DEFAULT_HTML}; reflects full --out history when given)",
    )
    parser.add_argument("--no-html", action="store_true", help="skip writing the HTML report")
    parser.add_argument(
        "--predictions",
        default=None,
        help="write SWE-bench predictions JSONL (for the official grading harness)",
    )
    parser.add_argument(
        "--grade",
        action="store_true",
        help="grade SWE-bench predictions with the official Docker harness (implies --predictions)",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="stream the agent transcript to stdout"
    )
    args = parser.parse_args(argv)

    try:
        tasks = get_suite(args.suite)
    except KeyError as exc:
        print(exc, file=sys.stderr)
        return 2

    if args.limit is not None:
        tasks = tasks[: args.limit]

    if not args.verbose:
        _silence_transcript()

    # Resolve the model list: --ollama-all discovers them, --models is an explicit
    # comma list, and either triggers the multi-model comparison path. A bare
    # --model (or nothing) keeps the original single-run behaviour.
    models = _resolve_models(args)
    if models is not None:
        return _run_comparison(args, tasks, models)

    print(f"Running suite '{args.suite}' ({len(tasks)} tasks)...\n")
    results = asyncio.run(run_suite(tasks, model=args.model))
    print("\n" + format_report(results))

    if args.out:
        append_run(args.out, results, model=args.model, timestamp=datetime.now().isoformat())
        print(f"\nResults appended to {args.out}")

    html_target = _html_target(args)
    if html_target:
        _emit_html(html_target, args.out, _records_for(results, args.model))

    predictions_path = args.predictions or ("predictions.jsonl" if args.grade else None)
    if predictions_path:
        from evals.suites.swebench import write_predictions

        write_predictions(Path(predictions_path), results, model=args.model)
        print(f"\nPredictions written to {predictions_path}.")
        if args.grade:
            return _grade(predictions_path, args.model)
        print(
            "Grade them with the official Docker harness:\n"
            f"  uv run python -m evals.swebench_grade --predictions {predictions_path} "
            "--run-id my-run\n"
            "Note: for the 'swebench' suite, PASS above means 'a patch was "
            "produced', not that the issue is resolved."
        )

    return 0 if all(r.passed for r in results) else 1


def _grade(predictions_path: str, model: str | None) -> int:
    """Grade a predictions file with the official harness; return a CI-style code.

    Exit 0 iff every submitted instance was genuinely resolved — so a graded run
    is a real correctness gate, not just a "patch produced" one.
    """
    from evals.swebench_grade import format_grade, grade_predictions

    run_id = f"evals-{datetime.now():%Y%m%d-%H%M%S}"
    print(f"\nGrading with the official harness (Docker), run_id={run_id} ...\n")
    try:
        report = grade_predictions(Path(predictions_path), run_id)
    except Exception as exc:  # missing Docker, missing swebench, harness crash
        print(f"Grading failed: {exc}", file=sys.stderr)
        return 1
    print("\n" + format_grade(report))
    return 0 if report.submitted and report.resolved == report.submitted else 1


if __name__ == "__main__":
    raise SystemExit(main())
