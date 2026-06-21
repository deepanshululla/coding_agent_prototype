---
sidebar_position: 2
title: The Harness
description: The Task / grader / run_task model at the core of every eval, what a result records, and how to write your own task.
---

# The Harness

Every eval, in every suite, is built from the same three pieces: a **`Task`** describing the work, a **grader** that judges the result, and **`run_task`** which orchestrates one isolated run. Understand these and you understand the whole system — the suites are just collections of `Task`s.

## A Task

A `Task` (`evals/harness.py`) pairs a natural-language prompt with the files the agent starts from and the grader that judges what it produced.

```python
@dataclass
class Task:
    id: str
    prompt: str
    grader: Grader
    files: dict[str, str] = field(default_factory=dict)   # seed files: path -> contents
    model: str | None = None                              # optional per-task model
    setup: Callable[[Path], None] | None = None           # optional pre-agent hook
```

- **`files`** are written into the workdir *before* the agent runs — the stub to fill in, the hidden test, a data file to read.
- **`setup`** is an escape hatch for setup that static files can't express — most importantly **cloning a repo at a commit** (see [SWE-bench](./swebench-lite.md)). It runs in the workdir before the agent and may raise to fail the task.

## A grader

A grader is a pure callable `(workdir: Path) -> GradeResult`. It inspects the directory the agent left behind and returns a verdict. Because graders never touch the agent or a model, they're deterministic and cheap to unit-test. Three are built in (`evals/graders.py`):

| Grader | Passes when | Dimension |
|---|---|---|
| `pytest_grader(test_file=None)` | pytest succeeds in the workdir | Code correctness |
| `command_grader(cmd, expect_exit=0)` | a shell command exits as expected | Tool use / end-state |
| `file_contains(path, substring)` | a file exists and holds a substring | Quick structural check |

```python
@dataclass(frozen=True)
class GradeResult:
    passed: bool
    detail: str = ""            # human-readable "why"
    artifact: str | None = None # machine-readable output, e.g. a candidate diff
```

`artifact` carries grader output meant for a machine rather than a human — the SWE-bench grader uses it to return the candidate patch, kept separate from the human `detail`.

## run_task

`run_task(task, model=None)` is the orchestration around a single agent run:

1. create an isolated temp working directory,
2. write the task's seed `files` into it,
3. `chdir` in — the agent's tools are cwd-relative,
4. run `task.setup(workdir)` if present,
5. drive the agent via the in-process SDK, collecting every event,
6. sum token usage and derive tool-calling stats from those events,
7. grade the directory the agent left behind,
8. always restore the original cwd and clean up.

Any exception — a failed setup, a crashed agent, a grader error — is caught and turned into a failing result, so one bad task never aborts a whole suite.

## What a result records

```python
@dataclass
class EvalResult:
    task_id: str
    passed: bool
    detail: str
    total_tokens: int
    duration_s: float
    artifact: str | None = None     # grader artifact (e.g. a diff)
    tool_stats: ToolStats = ...      # tool-calling quality
```

`ToolStats` is derived purely from the run's event stream:

```python
@dataclass
class ToolStats:
    calls: int      # tools the model invoked
    errors: int     # results that came back is_error
    unknown: int    # subset whose name isn't a real tool (hallucinated)

    @property
    def error_rate(self) -> float: ...
```

This is the signal a tool-calling eval is really after: a clean tool-caller drives the task with few calls and zero errors; a weak one flails — many calls, high error rate, invented tool names.

## Persisting results

`evals/results.py`'s `append_run()` writes one JSONL record per task, tagged with the model and an ISO timestamp, appending so history accumulates across runs and models:

```json
{"timestamp": "...", "model": "claude-opus", "task_id": "add-function",
 "passed": true, "total_tokens": 465, "duration_s": 11.0, "detail": "...",
 "tool_calls": 1, "tool_errors": 0, "tool_unknown": 0}
```

Pass `--out runs.jsonl` to any run to collect these.

## Writing your own task

A suite is just a `list[Task]`. To add one, write tasks and register a loader in `evals/run.py`'s `SUITES`:

```python
from evals.graders import pytest_grader
from evals.harness import Task

MY_SUITE = [
    Task(
        id="reverse-string",
        prompt="Write reverse(s) in solution.py that reverses a string.",
        files={"test_solution.py": "from solution import reverse\n"
                                    "def test(): assert reverse('abc') == 'cba'\n"},
        grader=pytest_grader("test_solution.py"),
    ),
]
```

Follow the project's [TDD practice](../contributing/development-workflow.md): graders are pure, so test them directly; test the loader by building tasks from a fixture; mock the agent runner to test orchestration without spending tokens.

## Related pages

- [Benchmark suites](./benchmark-suites.md) — the built-in self-contained suites
- [SWE-bench Lite](./swebench-lite.md) — the `setup` hook and `artifact` in action
- [Using the agent as a library](../programmatic-usage/sdk.md) — the SDK seam the harness drives
