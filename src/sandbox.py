"""Worktree sandbox: run the agent in an isolated git branch.

Usage:
    from sandbox import run_in_worktree

    worktree = await run_in_worktree(task="add type hints to tools.py")
    # Inspect: git -C worktree diff HEAD
    # Merge:   git merge agent/task-<id>
    # Discard: git worktree remove worktree --force

The policy engine (Layer 12.3) controls *what* the agent may do; the worktree
controls *where* the effects land. They compose: an auto-mode agent can write
freely while every write stays confined to a throwaway branch you inspect
before merging.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path


async def run_in_worktree(
    task: str,
    base_dir: str = ".",
    *,
    auto_cleanup_on_failure: bool = False,
) -> Path:
    """Create a git worktree, run the agent inside it, return the worktree path.

    The agent's working directory is changed to the worktree for the duration
    of the run so every relative file operation lands inside it. The caller is
    responsible for reviewing and removing the worktree when done.

    If auto_cleanup_on_failure is True, the worktree is removed when the agent
    makes no commits (a partial run or error). Default: False — always keep the
    worktree so you can inspect partial results.

    Note: os.chdir is process-global, so concurrent run_in_worktree calls in the
    same process are not safe. For concurrency, thread an explicit cwd through
    run_agent and the subprocess.run calls in tools.py instead of using chdir.
    """
    from agent import run_agent  # imported here to avoid circular imports

    run_id = uuid.uuid4().hex[:8]
    repo_root = Path(base_dir).resolve()
    worktree_path = repo_root.parent / f"agent-run-{run_id}"
    branch = f"agent/task-{run_id}"

    # Create a linked worktree on a new branch (shares the .git object store).
    subprocess.run(
        ["git", "worktree", "add", str(worktree_path), "-b", branch],
        cwd=repo_root,
        check=True,
    )

    original_cwd = os.getcwd()
    os.chdir(worktree_path)
    try:
        await run_agent(task)
    finally:
        os.chdir(original_cwd)

    if auto_cleanup_on_failure:
        result = subprocess.run(
            ["git", "log", "HEAD", "--oneline", "-1"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=repo_root,
                check=False,
            )
            raise RuntimeError(
                f"Agent made no commits in worktree {worktree_path}; worktree removed."
            )

    return worktree_path


@dataclass
class WorktreeSandbox:
    """Adapter that roots all relative file paths inside a worktree root.

    Pass an instance to write_file / edit_file to enforce path confinement:
        sandbox.resolve(args["path"])
    raises PermissionError if the resolved path is outside self.root.

    This is a planned extension. The worktree approach alone (setting cwd so
    relative paths resolve inside the worktree) is sufficient for the common
    case; resolve() closes the rare absolute-path escape at the tool level. It
    is not yet wired into write_file / edit_file — that is a later follow-up.
    """

    root: Path

    def resolve(self, path: str) -> Path:
        resolved = (self.root / path).resolve()
        root = str(Path(self.root).resolve())
        if not str(resolved).startswith(root):
            raise PermissionError(
                f"Path escape attempt: {path!r} -> {resolved} (outside sandbox root {self.root})"
            )
        return resolved
