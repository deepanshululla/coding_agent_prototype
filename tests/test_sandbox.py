"""Phase 12.4 — Sandboxing (worktree isolation).

Integration tests for src/sandbox.py. These exercise *real* git worktrees on a
throwaway repo fixture; the LLM is not involved. The agent's behavior inside the
worktree is stubbed by monkeypatching agent.run_agent with a function that
performs a relative-path write — exactly what write_file / edit_file do once cwd
points at the worktree. This proves the write lands in the worktree branch and
the main working tree is untouched, which is the whole point of this layer.

BDD scenario (from the plan / doc):

  Scenario: Agent writes land in a throwaway worktree, not the main working tree
    Given a git repository with a clean working tree
    And run_in_worktree is called with task "add a comment to tools.py"
    When the agent calls write_file or edit_file on "src/tools.py"
    Then the file is written inside the worktree directory
         (../agent-run-<id>/src/tools.py)
    And the file at src/tools.py in the main working tree is unchanged
    And run_in_worktree returns a Path pointing to the worktree
    And git -C <worktree> diff HEAD shows the agent's edit
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import pytest

import agent
import sandbox
from sandbox import WorktreeSandbox, run_in_worktree


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A throwaway git repo with one committed src/tools.py and a clean tree."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], cwd=repo)
    _git(["config", "user.email", "test@example.com"], cwd=repo)
    _git(["config", "user.name", "Test"], cwd=repo)
    src = repo / "src"
    src.mkdir()
    (src / "tools.py").write_text("# original tools.py\n")
    _git(["add", "-A"], cwd=repo)
    _git(["commit", "-m", "initial"], cwd=repo)
    return repo


def test_run_in_worktree_isolates_writes(git_repo, monkeypatch):
    """The agent's relative-path write lands in the worktree, not the main tree.

    Proves every clause of the BDD scenario: the worktree file carries the edit,
    the main tree's src/tools.py is byte-for-byte unchanged, and run_in_worktree
    returns a Path to a real worktree directory.
    """
    main_file = git_repo / "src" / "tools.py"
    original = main_file.read_text()

    async def fake_run_agent(task: str, *args, **kwargs):
        # cwd is the worktree (run_in_worktree chdir'd into it). A relative-path
        # write is what write_file / edit_file do — it must resolve here.
        Path("src/tools.py").write_text(original + "# agent comment\n")

    monkeypatch.setattr(agent, "run_agent", fake_run_agent)

    worktree = asyncio.run(run_in_worktree("add a comment to tools.py", base_dir=str(git_repo)))

    # run_in_worktree returns a Path pointing to a real worktree directory.
    assert isinstance(worktree, Path)
    assert worktree.is_dir()
    assert worktree != git_repo

    # The write landed inside the worktree.
    wt_file = worktree / "src" / "tools.py"
    assert wt_file.read_text() == original + "# agent comment\n"

    # The main working tree is unchanged — byte-for-byte.
    assert main_file.read_text() == original

    # git -C <worktree> diff HEAD shows the agent's edit.
    diff = _git(["-C", str(worktree), "diff", "HEAD"], cwd=worktree)
    assert "agent comment" in diff

    # The branch exists on the new worktree.
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=worktree).strip()
    assert branch.startswith("agent/task-")

    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree)],
        cwd=git_repo,
        check=False,
    )


def test_run_in_worktree_restores_cwd(git_repo, monkeypatch):
    """cwd is restored even though run_in_worktree chdir's into the worktree."""
    before = os.getcwd()

    async def fake_run_agent(task: str, *args, **kwargs):
        return None

    monkeypatch.setattr(agent, "run_agent", fake_run_agent)

    worktree = asyncio.run(run_in_worktree("noop", base_dir=str(git_repo)))
    assert os.getcwd() == before

    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree)],
        cwd=git_repo,
        check=False,
    )


def test_auto_cleanup_keeps_worktree_when_base_has_commits(git_repo, monkeypatch):
    """A worktree branched from a commit always has a non-empty HEAD log.

    The plan's auto_cleanup_on_failure check is `git log HEAD --oneline -1`:
    it removes the worktree only when that log is empty (an unborn branch with
    no reachable commit). Branching off a normal repo HEAD has the base commit,
    so the worktree is kept even with auto_cleanup_on_failure=True. This is the
    documented behavior; we assert it so the cleanup branch is exercised.
    """

    async def fake_run_agent(task: str, *args, **kwargs):
        return None

    monkeypatch.setattr(agent, "run_agent", fake_run_agent)

    worktree = run_in_worktree_sync(git_repo, auto_cleanup_on_failure=True)
    assert worktree.is_dir()

    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree)],
        cwd=git_repo,
        check=False,
    )


def test_auto_cleanup_on_failure_removes_worktree_on_unborn_branch(tmp_path, monkeypatch):
    """With auto_cleanup_on_failure and an empty HEAD log, the worktree is removed.

    We force the empty-log condition by stubbing subprocess.run for the
    `git log HEAD` probe to report no output, so the cleanup branch fires and
    RuntimeError is raised. This exercises the documented failure path without
    needing an unborn-branch worktree (which git refuses to create directly).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], cwd=repo)
    _git(["config", "user.email", "test@example.com"], cwd=repo)
    _git(["config", "user.name", "Test"], cwd=repo)
    (repo / "f.txt").write_text("x\n")
    _git(["add", "-A"], cwd=repo)
    _git(["commit", "-m", "initial"], cwd=repo)

    async def fake_run_agent(task: str, *args, **kwargs):
        return None

    monkeypatch.setattr(agent, "run_agent", fake_run_agent)

    real_run = subprocess.run

    def fake_subprocess_run(cmd, *args, **kwargs):
        # Make the HEAD-log probe report an empty log.
        if cmd[:3] == ["git", "log", "HEAD"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(sandbox.subprocess, "run", fake_subprocess_run)

    with pytest.raises(RuntimeError, match="no commits"):
        asyncio.run(run_in_worktree("noop", base_dir=str(repo), auto_cleanup_on_failure=True))

    # No leftover worktrees besides the main one.
    listing = real_run(
        ["git", "worktree", "list"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "agent-run-" not in listing


def run_in_worktree_sync(repo: Path, **kwargs) -> Path:
    return asyncio.run(run_in_worktree("noop", base_dir=str(repo), **kwargs))


def test_worktree_sandbox_resolve_allows_inside(tmp_path):
    sandbox_root = tmp_path / "wt"
    sandbox_root.mkdir()
    sb = WorktreeSandbox(root=sandbox_root)
    resolved = sb.resolve("src/tools.py")
    assert str(resolved).startswith(str(sandbox_root.resolve()))


def test_worktree_sandbox_resolve_rejects_escape(tmp_path):
    sandbox_root = tmp_path / "wt"
    sandbox_root.mkdir()
    sb = WorktreeSandbox(root=sandbox_root)
    with pytest.raises(PermissionError, match="Path escape"):
        sb.resolve("../../etc/passwd")


def test_module_exports_run_in_worktree():
    assert callable(sandbox.run_in_worktree)
