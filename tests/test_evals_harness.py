"""Tests for the eval harness orchestration.

The harness owns everything *around* a single agent run: it stands up an
isolated temp workdir, drops in the task's seed files, points the agent at that
dir, sums the token usage the run emitted, grades the result, and always
restores the original cwd. None of that needs a real model — we monkeypatch the
agent runner with a fake that simulates the file writes a real run would make,
so the tests are fast and deterministic.
"""

import asyncio
from pathlib import Path

import evals.harness as harness
from evals.graders import file_contains
from evals.harness import EvalResult, Task, run_task


def _fake_runner(write: dict[str, str], usage_total: int = 0):
    """Build a stand-in for sdk.run_agent_collecting.

    It writes ``write`` (relative path -> contents) into the *current* cwd —
    mimicking an agent that edited files — and returns (events, messages) with
    the requested token usage folded into a turn_end event.
    """

    async def fake(task, **kwargs):
        for rel, contents in write.items():
            target = Path(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents)
        events = [
            {"type": "turn_end", "usage": {"total_tokens": usage_total}},
            {"type": "agent_end"},
        ]
        return events, []

    return fake


def test_run_task_passes_when_agent_satisfies_grader(monkeypatch, tmp_path):
    monkeypatch.setattr(harness, "run_agent_collecting", _fake_runner({"out.txt": "hello world"}))
    task = Task(
        id="writes-file",
        prompt="write hello world to out.txt",
        grader=file_contains("out.txt", "hello world"),
    )
    result = asyncio.run(run_task(task))
    assert isinstance(result, EvalResult)
    assert result.task_id == "writes-file"
    assert result.passed is True


def test_run_task_fails_when_grader_rejects(monkeypatch, tmp_path):
    monkeypatch.setattr(harness, "run_agent_collecting", _fake_runner({"out.txt": "wrong"}))
    task = Task(
        id="bad",
        prompt="...",
        grader=file_contains("out.txt", "hello world"),
    )
    result = asyncio.run(run_task(task))
    assert result.passed is False


def test_run_task_records_token_usage(monkeypatch, tmp_path):
    monkeypatch.setattr(
        harness, "run_agent_collecting", _fake_runner({"out.txt": "x"}, usage_total=1234)
    )
    task = Task(id="t", prompt="p", grader=file_contains("out.txt", "x"))
    result = asyncio.run(run_task(task))
    assert result.total_tokens == 1234


def test_run_task_isolates_and_restores_cwd(monkeypatch, tmp_path):
    before = Path.cwd()
    monkeypatch.setattr(harness, "run_agent_collecting", _fake_runner({"out.txt": "x"}))
    task = Task(id="t", prompt="p", grader=file_contains("out.txt", "x"))
    asyncio.run(run_task(task))
    assert Path.cwd() == before


def test_run_task_seed_files_are_present_for_the_agent(monkeypatch, tmp_path):
    """Seed files are written before the agent runs, in the same workdir."""
    seen = {}

    async def fake(task, **kwargs):
        seen["seed"] = Path("seed.txt").read_text()
        Path("out.txt").write_text("ok")
        return [{"type": "agent_end"}], []

    monkeypatch.setattr(harness, "run_agent_collecting", fake)
    task = Task(
        id="t",
        prompt="p",
        files={"seed.txt": "from-seed"},
        grader=file_contains("out.txt", "ok"),
    )
    asyncio.run(run_task(task))
    assert seen["seed"] == "from-seed"


def test_run_task_restores_cwd_even_when_agent_raises(monkeypatch, tmp_path):
    before = Path.cwd()

    async def boom(task, **kwargs):
        raise RuntimeError("agent exploded")

    monkeypatch.setattr(harness, "run_agent_collecting", boom)
    task = Task(id="t", prompt="p", grader=file_contains("out.txt", "x"))
    result = asyncio.run(run_task(task))
    assert Path.cwd() == before
    assert result.passed is False
    assert "exploded" in result.detail


def test_run_task_forwards_model_to_runner(monkeypatch, tmp_path):
    captured = {}

    async def fake(task, **kwargs):
        captured.update(kwargs)
        Path("out.txt").write_text("x")
        return [{"type": "agent_end"}], []

    monkeypatch.setattr(harness, "run_agent_collecting", fake)
    task = Task(id="t", prompt="p", grader=file_contains("out.txt", "x"))
    asyncio.run(run_task(task, model="gpt-4o"))
    assert captured["model"] == "gpt-4o"


def test_run_task_runs_setup_before_the_agent_in_the_workdir(monkeypatch, tmp_path):
    """A task's setup hook runs in the workdir before the agent, e.g. to clone a repo."""
    order = []

    def setup(workdir: Path):
        order.append("setup")
        (workdir / "from_setup.txt").write_text("prepared")

    async def fake(task, **kwargs):
        order.append("agent")
        # The agent sees what setup produced, in the cwd.
        assert Path("from_setup.txt").read_text() == "prepared"
        Path("out.txt").write_text("ok")
        return [{"type": "agent_end"}], []

    monkeypatch.setattr(harness, "run_agent_collecting", fake)
    task = Task(id="t", prompt="p", grader=file_contains("out.txt", "ok"), setup=setup)
    result = asyncio.run(run_task(task))
    assert order == ["setup", "agent"]
    assert result.passed is True


def test_run_task_failed_setup_fails_the_task_without_running_agent(monkeypatch, tmp_path):
    ran_agent = []

    def setup(workdir: Path):
        raise RuntimeError("clone failed")

    async def fake(task, **kwargs):
        ran_agent.append(True)
        return [{"type": "agent_end"}], []

    monkeypatch.setattr(harness, "run_agent_collecting", fake)
    task = Task(id="t", prompt="p", grader=file_contains("out.txt", "x"), setup=setup)
    result = asyncio.run(run_task(task))
    assert ran_agent == []
    assert result.passed is False
    assert "clone failed" in result.detail


def test_run_task_runs_agent_under_allow_all_policy(monkeypatch, tmp_path):
    """Eval tasks run in throwaway temp dirs, so the harness lifts the permission
    gate for the duration of the run (otherwise write_file/edit_file are denied
    non-interactively) and restores the prior policy afterward."""
    import agent
    from policy import PolicyEngine

    seen = {}

    async def fake(task, **kwargs):
        seen["default"] = agent._policy.default
        Path("out.txt").write_text("x")
        return [{"type": "agent_end"}], []

    monkeypatch.setattr(harness, "run_agent_collecting", fake)
    # monkeypatch.setattr so the global agent._policy is restored after the test
    # (a bare assignment would leak this restrictive engine into later tests).
    monkeypatch.setattr(agent, "_policy", PolicyEngine([], default="deny"))
    task = Task(id="t", prompt="p", grader=file_contains("out.txt", "x"))
    asyncio.run(run_task(task))
    assert seen["default"] == "allow"  # the agent ran permissively
    assert agent._policy.default == "deny"  # and the prior policy is restored


def test_run_task_counts_iterations_from_turn_end_events(monkeypatch, tmp_path):
    async def fake(task, **kwargs):
        Path("out.txt").write_text("x")
        return (
            [
                {"type": "turn_end", "usage": {"total_tokens": 1}},
                {"type": "turn_end", "usage": {"total_tokens": 1}},
                {"type": "turn_end", "usage": {"total_tokens": 1}},
                {"type": "agent_end"},
            ],
            [],
        )

    monkeypatch.setattr(harness, "run_agent_collecting", fake)
    task = Task(id="t", prompt="p", grader=file_contains("out.txt", "x"))
    result = asyncio.run(run_task(task))
    assert result.iterations == 3


def test_run_task_grades_answer_when_grader_wants_it(monkeypatch, tmp_path):
    """An answer-grader (wants_answer=True) is fed the run's final assistant text,
    captured from the returned messages — not the workdir."""

    async def fake(task, **kwargs):
        # No files written; the answer lives only in the final assistant message.
        return (
            [{"type": "turn_end", "usage": {"total_tokens": 1}}],
            [
                {"role": "user", "content": "p"},
                {"role": "assistant", "content": "reasoning...\nThe answer is 42"},
            ],
        )

    monkeypatch.setattr(harness, "run_agent_collecting", fake)

    seen = {}

    def answer_grader(answer):
        from evals.graders import GradeResult

        seen["answer"] = answer
        return GradeResult("42" in answer, "ok")

    answer_grader.wants_answer = True  # ty: ignore[unresolved-attribute]
    task = Task(id="t", prompt="p", grader=answer_grader)
    result = asyncio.run(run_task(task))
    assert result.passed is True
    assert "The answer is 42" in seen["answer"]
    assert result.answer  # the captured answer is recorded on the result


def test_run_task_surfaces_grader_artifact(monkeypatch, tmp_path):
    """A grader can attach a machine-readable artifact (e.g. a diff) to the result."""
    from evals.graders import GradeResult

    async def fake(task, **kwargs):
        Path("out.txt").write_text("x")
        return [{"type": "agent_end"}], []

    monkeypatch.setattr(harness, "run_agent_collecting", fake)
    task = Task(
        id="t",
        prompt="p",
        grader=lambda workdir: GradeResult(True, "done", artifact="THE-PATCH"),
    )
    result = asyncio.run(run_task(task))
    assert result.artifact == "THE-PATCH"
