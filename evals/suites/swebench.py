"""SWE-bench Lite as eval `Task`s — the *prediction* half of the benchmark.

SWE-bench gives a real GitHub issue and the repo at a base commit; a solution is
a patch that makes the project's hidden tests pass. Grading is necessarily a
separate batch step: the official harness builds a per-instance Docker image with
that project's exact dependencies, applies the test patch, and runs the target
tests. Reproducing that environment matrix in-process would be flaky, so we don't
try — we **produce predictions** and hand them to the official harness.

This module:

1. fetches instances (dependency-free, via the HF datasets-server JSON API),
2. builds a `Task` per instance whose ``setup`` clones the repo at the base
   commit and whose grader captures the agent's diff as the candidate patch,
3. writes those diffs as a SWE-bench ``predictions.jsonl``.

Then grade with the canonical harness (Docker required)::

    python -m swebench.harness.run_evaluation \
        --dataset_name princeton-nlp/SWE-bench_Lite \
        --predictions_path predictions.jsonl \
        --run_id my-run

The inline pass/fail this suite reports means only "a non-empty patch was
produced" — real correctness comes from the harness run above.
"""

from __future__ import annotations

import json
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from evals.graders import Grader, GradeResult
from evals.harness import Task

DATASET = "princeton-nlp/SWE-bench_Lite"
DATASETS_SERVER = "https://datasets-server.huggingface.co/rows"


@dataclass(frozen=True)
class Instance:
    """One SWE-bench task instance, with the test lists already JSON-decoded."""

    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    test_patch: str
    fail_to_pass: list[str]
    pass_to_pass: list[str]


def parse_instances(rows: list[dict]) -> list[Instance]:
    """Turn raw dataset rows into `Instance`s.

    The dataset stores FAIL_TO_PASS / PASS_TO_PASS as JSON-encoded strings; decode
    them (tolerating rows where they're already lists).
    """

    def _as_list(value) -> list[str]:
        if isinstance(value, list):
            return value
        return json.loads(value) if value else []

    return [
        Instance(
            instance_id=row["instance_id"],
            repo=row["repo"],
            base_commit=row["base_commit"],
            problem_statement=row["problem_statement"],
            test_patch=row.get("test_patch", ""),
            fail_to_pass=_as_list(row.get("FAIL_TO_PASS")),
            pass_to_pass=_as_list(row.get("PASS_TO_PASS")),
        )
        for row in rows
    ]


def github_url(repo: str) -> str:
    """Clone URL for a ``owner/name`` repo."""
    return f"https://github.com/{repo}.git"


def fetch_instances(limit: int = 5, offset: int = 0) -> list[Instance]:
    """Fetch a slice of SWE-bench Lite via the datasets-server (no heavy deps).

    The endpoint caps at 100 rows per request, which is plenty for a slice.
    """
    query = urllib.parse.urlencode(
        {
            "dataset": DATASET,
            "config": "default",
            "split": "test",
            "offset": offset,
            "length": min(limit, 100),
        }
    )
    with urllib.request.urlopen(f"{DATASETS_SERVER}?{query}") as resp:
        payload = json.load(resp)
    rows = [r["row"] for r in payload.get("rows", [])]
    return parse_instances(rows)


def clone_setup(clone_url: str, base_commit: str):
    """Build a `Task.setup` that puts ``clone_url`` @ ``base_commit`` in the workdir.

    Uses fetch-by-sha so only the one commit is downloaded (GitHub allows this),
    leaving the workdir as a git repo checked out at the base commit — exactly the
    starting state SWE-bench defines.
    """

    def setup(workdir: Path) -> None:
        def git(*args):
            subprocess.run(["git", *args], cwd=workdir, check=True, capture_output=True, text=True)

        git("init", "-q")
        git("remote", "add", "origin", clone_url)
        git("fetch", "-q", "--depth", "1", "origin", base_commit)
        git("checkout", "-q", "FETCH_HEAD")

    return setup


def capture_patch_grader() -> Grader:
    """Grader that captures the agent's edits as a diff against the base commit.

    Stages everything (so new files are included, as SWE-bench patches expect) and
    diffs against HEAD. ``passed`` is True iff the patch is non-empty — a proxy for
    "the agent attempted a fix"; real correctness is decided by the official
    harness run over the predictions file.
    """

    def grade(workdir: Path) -> GradeResult:
        subprocess.run(
            ["git", "add", "-A"], cwd=workdir, check=True, capture_output=True, text=True
        )
        diff = subprocess.run(
            ["git", "diff", "--cached"],
            cwd=workdir,
            capture_output=True,
            text=True,
        ).stdout
        if diff.strip():
            n = diff.count("\ndiff --git")
            return GradeResult(True, f"patch produced ({n + 1} file(s))", artifact=diff)
        return GradeResult(False, "no patch produced", artifact="")

    return grade


def load_swebench(instances: list[Instance]) -> list[Task]:
    """Build one `Task` per instance: clone at base commit, agent edits, capture diff."""
    tasks: list[Task] = []
    for inst in instances:
        prompt = (
            f"{inst.problem_statement.strip()}\n\n"
            "This is a checkout of the repository at the commit where the issue was "
            "reported. Investigate the codebase, find the root cause, and edit the "
            "source files to resolve the issue. Do not modify any tests."
        )
        tasks.append(
            Task(
                id=inst.instance_id,
                prompt=prompt,
                grader=capture_patch_grader(),
                setup=clone_setup(github_url(inst.repo), inst.base_commit),
            )
        )
    return tasks


def write_predictions(path: Path, results, model: str | None) -> None:
    """Write SWE-bench predictions JSONL: one {instance_id, model_name_or_path,
    model_patch} record per result, ready for the official evaluation harness."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in results:
            record = {
                "instance_id": r.task_id,
                "model_name_or_path": model or "agent",
                "model_patch": r.artifact or "",
            }
            fh.write(json.dumps(record) + "\n")
