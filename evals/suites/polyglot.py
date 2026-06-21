"""Aider polyglot benchmark as eval `Task`s.

The polyglot-benchmark repo holds Exercism exercises across six languages. Each
exercise gives a problem statement, a stub the agent fills in, and a hidden test
suite; we grade by running those tests. This is the recommended first *real*
benchmark for the agent — self-contained (no per-exercise repo setup) yet a
genuine multi-file edit-then-test loop.

Only Python is wired up so far (its tests run with the same pytest the eval
harness already uses). Other languages slot in by adding an entry to
:data:`_LANGUAGES` with that language's test command and file conventions.

Use :func:`ensure_polyglot_repo` to sparse-clone the exercises on demand, then
:func:`load_polyglot` to turn them into `Task`s.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from evals.graders import Grader, pytest_grader
from evals.harness import Task

POLYGLOT_REPO = "https://github.com/Aider-AI/polyglot-benchmark"
#: Where ensure_polyglot_repo() caches the checkout (gitignored).
DEFAULT_CACHE = Path(__file__).resolve().parent.parent / ".cache" / "polyglot-benchmark"


@dataclass(frozen=True)
class LanguageSpec:
    """How to recognise and grade exercises for one language."""

    #: Suffix that marks a test file (e.g. "_test.py").
    test_suffix: str
    #: Build a grader given the test filenames found in the exercise.
    make_grader: Callable[[list[str]], Grader]


_LANGUAGES: dict[str, LanguageSpec] = {
    "python": LanguageSpec(
        test_suffix="_test.py",
        make_grader=lambda tests: pytest_grader(),  # collect every test in the dir
    ),
}


def ensure_polyglot_repo(cache_dir: Path = DEFAULT_CACHE, languages=("python",)) -> Path:
    """Sparse-clone the polyglot benchmark into ``cache_dir`` if not already there.

    Only the requested language subtrees are checked out to keep it small. A
    pre-existing checkout is left untouched (idempotent). Returns the repo root.
    """
    if (cache_dir / ".git").exists():
        return cache_dir
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--filter=blob:none",
            "--sparse",
            POLYGLOT_REPO,
            str(cache_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(cache_dir), "sparse-checkout", "set", *languages],
        check=True,
        capture_output=True,
        text=True,
    )
    return cache_dir


def _read(path: Path) -> str:
    return path.read_text() if path.exists() else ""


def _build_task(language: str, slug: str, exercise: Path, spec: LanguageSpec) -> Task | None:
    """Turn one exercise directory into a `Task`, or None if it looks malformed."""
    # Source files the agent sees: every top-level source file, stub + tests, but
    # never anything under .meta (which holds the reference solution).
    sources = sorted(p for p in exercise.iterdir() if p.is_file() and p.suffix)
    test_files = [p.name for p in sources if p.name.endswith(spec.test_suffix)]
    solution_files = [p.name for p in sources if not p.name.endswith(spec.test_suffix)]
    if not test_files or not solution_files:
        return None

    instructions = _read(exercise / ".docs" / "instructions.md")
    instructions += "\n" + _read(exercise / ".docs" / "instructions.append.md")

    prompt = (
        f"{instructions.strip()}\n\n"
        f"Implement your solution in {', '.join(solution_files)}. "
        f"Do not modify the test file(s): {', '.join(test_files)}. "
        f"Run the tests to check your work."
    )

    files = {p.name: p.read_text() for p in sources}
    grader: Grader = spec.make_grader(test_files)

    return Task(id=f"{language}/{slug}", prompt=prompt, grader=grader, files=files)


def load_polyglot(repo_path: Path, languages=("python",)) -> list[Task]:
    """Walk a checked-out polyglot repo and build one `Task` per exercise.

    Exercises with an unrecognised language, or missing a stub or test file, are
    skipped. Tasks come back sorted by id for stable, resumable runs.
    """
    tasks: list[Task] = []
    for language in languages:
        spec = _LANGUAGES.get(language)
        if spec is None:
            continue
        practice = repo_path / language / "exercises" / "practice"
        if not practice.is_dir():
            continue
        for exercise in practice.iterdir():
            if not exercise.is_dir():
                continue
            task = _build_task(language, exercise.name, exercise, spec)
            if task is not None:
                tasks.append(task)
    return sorted(tasks, key=lambda t: t.id)
