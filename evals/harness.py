"""The eval harness — run one task against the agent and grade the result.

A :class:`Task` pairs a natural-language prompt with the seed files the agent
starts from and a grader that judges what it produced. :func:`run_task` is the
orchestration around a single agent run:

1. stand up an isolated temp working directory,
2. write the task's seed files into it,
3. ``chdir`` in (the agent's tools are cwd-relative — see ``main.py``),
4. drive the agent via the in-process SDK, collecting its events,
5. sum the token usage those events reported,
6. grade the directory the agent left behind,
7. always restore the original cwd and clean up.

The agent runner is referenced as the module-level :data:`run_agent_collecting`
so tests can monkeypatch it with a fake — no model call, no API cost.
"""

from __future__ import annotations

import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from evals.graders import Grader
from sdk import run_agent_collecting


@dataclass
class Task:
    """One eval case: a prompt, the files it starts from, and how to grade it."""

    id: str
    prompt: str
    grader: Grader
    #: Seed files written into the workdir before the agent runs: path -> text.
    files: dict[str, str] = field(default_factory=dict)
    #: Optional per-task model override (else the configured/default model).
    model: str | None = None
    #: Optional hook run in the workdir before the agent, for setup that static
    #: seed files can't express — e.g. cloning a repo at a commit (SWE-bench).
    #: Receives the workdir Path. A raised exception fails the task.
    setup: Callable[[Path], None] | None = None


@dataclass
class ToolStats:
    """Tool-calling quality for one run, derived from the event stream.

    ``calls`` is how many tools the model invoked; ``errors`` how many came back
    is_error (a failed dispatch, bad arguments, or a hallucinated name); and
    ``unknown`` the subset whose name isn't a real tool at all (the model made
    one up). A clean tool-caller drives the task with few calls and zero
    errors/unknowns; a weak one flails — many calls, high error rate, invented
    tool names. This is the signal a tool-calling eval is really after.
    """

    calls: int = 0
    errors: int = 0
    unknown: int = 0

    @property
    def error_rate(self) -> float:
        return self.errors / self.calls if self.calls else 0.0


@dataclass
class EvalResult:
    """The outcome of running one task: verdict, cost, timing, tool quality."""

    task_id: str
    passed: bool
    detail: str
    total_tokens: int
    duration_s: float
    #: Optional machine-readable grader output (e.g. a candidate diff).
    artifact: str | None = None
    #: Tool-calling quality derived from the run's events.
    tool_stats: ToolStats = field(default_factory=ToolStats)
    #: Model turns taken to finish (one per turn_end) — steps-to-solution.
    iterations: int = 0
    #: The run's final assistant answer (used by answer-graders; recorded for
    #: debugging reasoning tasks where the verdict is the spoken answer).
    answer: str = ""


def _sum_usage(events: list[dict]) -> int:
    """Total the ``total_tokens`` reported across every turn_end event."""
    total = 0
    for event in events:
        usage = event.get("usage") if isinstance(event, dict) else None
        if usage:
            total += int(usage.get("total_tokens") or 0)
    return total


def _count_iterations(events: list[dict]) -> int:
    """Number of model turns the run took — one ``turn_end`` per turn."""
    return sum(1 for e in events if isinstance(e, dict) and e.get("type") == "turn_end")


def _final_answer(messages: list[dict]) -> str:
    """The run's final spoken answer: the last assistant message with str content.

    Reasoning tasks are graded on what the model *said*, not files it wrote, so we
    pull the closing assistant turn out of the returned message history. Returns
    "" when there is no plain-text assistant turn (e.g. the run only made tool
    calls), which an answer-grader treats as a miss.
    """
    for message in reversed(messages or []):
        if message.get("role") == "assistant" and isinstance(message.get("content"), str):
            return message["content"]
    return ""


def tool_stats(events: list[dict]) -> ToolStats:
    """Derive :class:`ToolStats` from the collected events of one run.

    Counts ``tool_call_start`` events as calls and ``tool_call_end`` events with
    ``is_error`` as errors; an error whose content begins with ``"Unknown tool"``
    is additionally counted as a hallucinated (unknown) tool name. Pure function
    of the event list, so it's deterministic and cheap to test.
    """
    calls = errors = unknown = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        etype = event.get("type")
        if etype == "tool_call_start":
            calls += 1
        elif etype == "tool_call_end" and event.get("is_error"):
            errors += 1
            content = event.get("content")
            if isinstance(content, str) and content.startswith("Unknown tool"):
                unknown += 1
    return ToolStats(calls=calls, errors=errors, unknown=unknown)


async def run_task(task: Task, model: str | None = None) -> EvalResult:
    """Run ``task`` in an isolated workdir and return its graded result.

    ``model`` overrides the task's own ``model`` (which itself overrides the
    configured default). Any exception from the agent run is caught and turned
    into a failing result so one bad task never aborts a suite.
    """
    chosen_model = model or task.model
    original_cwd = Path.cwd()
    start = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="eval-") as tmp:
        workdir = Path(tmp)
        for rel, contents in task.files.items():
            target = workdir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents)

        os.chdir(workdir)
        tokens, artifact, stats, iterations, answer = 0, None, ToolStats(), 0, ""
        # Lift the permission gate for the run: the workdir is a throwaway temp
        # dir, and the non-interactive postures would otherwise block writes
        # (auto denies write_file/edit_file; ask would block on stdin). Restored
        # in the finally so a swapped-in policy never leaks across tasks.
        import agent
        from policy import PolicyEngine

        saved_policy = agent._policy
        agent._policy = PolicyEngine([], default="allow")
        try:
            if task.setup is not None:
                task.setup(workdir)
            kwargs = {}
            if chosen_model is not None:
                kwargs["model"] = chosen_model
            events, messages = await run_agent_collecting(task.prompt, **kwargs)
            tokens = _sum_usage(events)
            stats = tool_stats(events)
            iterations = _count_iterations(events)
            answer = _final_answer(messages)
            # An answer-grader (wants_answer=True) judges the spoken answer;
            # every other grader inspects the workdir the agent left behind.
            if getattr(task.grader, "wants_answer", False):
                verdict = task.grader(answer)
            else:
                verdict = task.grader(workdir)
            passed, detail, artifact = verdict.passed, verdict.detail, verdict.artifact
        except Exception as exc:  # one task's failure must not abort the suite
            passed, detail = False, f"task raised: {exc}"
        finally:
            agent._policy = saved_policy
            os.chdir(original_cwd)

    return EvalResult(
        task_id=task.id,
        passed=passed,
        detail=detail,
        total_tokens=tokens,
        duration_s=time.monotonic() - start,
        artifact=artifact,
        tool_stats=stats,
        iterations=iterations,
        answer=answer,
    )
