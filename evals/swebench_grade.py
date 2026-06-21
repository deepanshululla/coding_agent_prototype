"""Grade SWE-bench predictions with the official harness (Docker required).

This is the second half of the SWE-bench flow (see ``evals/suites/swebench.py``
for the first). Given a ``predictions.jsonl`` produced by a ``swebench`` eval run,
it shells out to the canonical evaluator::

    python -m swebench.harness.run_evaluation \
        --dataset_name princeton-nlp/SWE-bench_Lite \
        --predictions_path predictions.jsonl --run_id <id>

The harness builds a per-instance Docker image, applies that instance's test
patch, runs the target tests, and writes a report JSON named
``<model>.<run_id>.json`` into the working directory. We locate that report and
parse it into a :class:`GradeReport` with the true *resolved* rate.

Run it directly::

    python -m evals.swebench_grade --predictions preds.jsonl --run-id my-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

DATASET = "princeton-nlp/SWE-bench_Lite"


@dataclass
class GradeReport:
    """The official harness's verdict over a predictions file."""

    submitted: int
    resolved: int
    resolved_ids: list[str] = field(default_factory=list)
    unresolved_ids: list[str] = field(default_factory=list)
    error_ids: list[str] = field(default_factory=list)

    @property
    def resolved_rate(self) -> float:
        """Resolved as a fraction of *submitted* (the slice), not the full dataset."""
        return self.resolved / self.submitted if self.submitted else 0.0


def parse_report(report: dict) -> GradeReport:
    """Turn a swebench run-report dict into a :class:`GradeReport`.

    Prefers the ``*_instances`` counts; falls back to the lengths of the
    corresponding id lists when those counts are absent.
    """
    resolved_ids = report.get("resolved_ids", [])
    unresolved_ids = report.get("unresolved_ids", [])
    error_ids = report.get("error_ids", [])
    submitted = report.get("submitted_instances")
    if submitted is None:
        submitted = len(report.get("submitted_ids", []))
    resolved = report.get("resolved_instances")
    if resolved is None:
        resolved = len(resolved_ids)
    return GradeReport(
        submitted=submitted,
        resolved=resolved,
        resolved_ids=resolved_ids,
        unresolved_ids=unresolved_ids,
        error_ids=error_ids,
    )


def find_report(run_id: str, directory: Path) -> Path | None:
    """Locate the ``<model>.<run_id>.json`` report the harness wrote, or None."""
    matches = sorted(Path(directory).glob(f"*.{run_id}.json"))
    return matches[0] if matches else None


#: Harness ``--predictions_path`` values that are sentinels, not files.
_PREDICTION_SENTINELS = ("gold", "None")


def _eval_command(
    predictions_path,
    run_id: str,
    dataset: str,
    instance_ids: list[str] | None,
    max_workers: int,
) -> list[str]:
    """Build the ``run_evaluation`` argv. Sentinels (``gold``/``None``) pass through
    verbatim; real paths are resolved to absolute (the harness runs with cwd set to
    the workdir, so a relative predictions path would otherwise break)."""
    pred = str(predictions_path)
    pred_arg = pred if pred in _PREDICTION_SENTINELS else str(Path(pred).resolve())
    cmd = [
        sys.executable,
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        dataset,
        "--predictions_path",
        pred_arg,
        "--run_id",
        run_id,
        "--max_workers",
        str(max_workers),
    ]
    if instance_ids:
        cmd += ["--instance_ids", *instance_ids]
    return cmd


def grade_predictions(
    predictions_path: Path,
    run_id: str,
    *,
    dataset: str = DATASET,
    instance_ids: list[str] | None = None,
    max_workers: int = 4,
    workdir: Path | None = None,
) -> GradeReport:
    """Run the official harness over ``predictions_path`` and parse its report.

    Requires the ``swebench`` package installed and a running Docker daemon. Raises
    ``FileNotFoundError`` if the harness produces no report (e.g. it crashed before
    writing one — its own logs explain why).
    """
    workdir = Path(workdir) if workdir else Path.cwd()
    cmd = _eval_command(predictions_path, run_id, dataset, instance_ids, max_workers)
    subprocess.run(cmd, check=True, cwd=workdir)

    report_file = find_report(run_id, workdir)
    if report_file is None:
        raise FileNotFoundError(
            f"no report '<model>.{run_id}.json' in {workdir}; "
            "check the harness output above for the failure."
        )
    return parse_report(json.loads(report_file.read_text()))


def format_grade(report: GradeReport) -> str:
    """Human summary of a grading run."""
    lines = [
        f"Resolved {report.resolved}/{report.submitted} "
        f"({report.resolved_rate:.0%}) of submitted instances",
    ]
    if report.resolved_ids:
        lines.append("  resolved:   " + ", ".join(report.resolved_ids))
    if report.unresolved_ids:
        lines.append("  unresolved: " + ", ".join(report.unresolved_ids))
    if report.error_ids:
        lines.append("  errored:    " + ", ".join(report.error_ids))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Grade SWE-bench predictions with the official Docker harness."
    )
    parser.add_argument("--predictions", required=True, help="path to predictions.jsonl")
    parser.add_argument("--run-id", required=True, help="run id (names the report file)")
    parser.add_argument("--dataset", default=DATASET, help="HF dataset name")
    parser.add_argument("--max-workers", type=int, default=4)
    args = parser.parse_args(argv)

    try:
        report = grade_predictions(
            Path(args.predictions),
            args.run_id,
            dataset=args.dataset,
            max_workers=args.max_workers,
        )
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    print("\n" + format_grade(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
