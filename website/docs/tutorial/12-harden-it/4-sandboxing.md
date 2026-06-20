---
sidebar_position: 4
title: "Layer 12.4 — Sandboxing"
description: Isolate the agent's file writes in a throwaway git worktree (or container) so a bad run never touches your main working tree, and you review the diff before merging.
---

# Layer 12.4 — Sandboxing

:::note Implemented
This step is implemented on branch `step/phase-12-4-sandboxing` (plan: `plans/tutorial/phase-12-4-sandboxing.md`).
:::

:::note Starting point
The agent from Layer 12.3: a `PolicyEngine` gates every tool call and `AGENT_PERMISSION_MODE` selects the operating posture. The agent can now be locked read-only or prompted before writes. But when it does write — in `ask` or `auto` mode — those writes land directly in your main working tree. A partial refactor, a wrong path, or a half-completed edit leaves your tree damaged.
:::

The policy engine controls *what* the agent is allowed to do. Sandboxing controls *where* the effects land. The two are independent and compose: you can allow the agent to write freely (auto mode) while still keeping those writes isolated in a throwaway branch that you inspect before merging.

This layer adds a **git worktree wrapper** around `run_agent`. The agent works exclusively in a linked checkout on a fresh branch; your main working tree is untouched. After the run, you `git diff` the result and merge what looks good.

The design is covered in [Worktrees](../../architecture-patterns/worktrees.md). For container-level process and network isolation (a complementary control), see [Containerization](../../operations/containerization.md).

## What you'll learn

- How a git worktree gives the agent its own branch while sharing the same `.git` object store.
- How to set `cwd` before calling `run_agent` so all relative file operations stay inside the worktree.
- Why worktrees and containers solve different problems and compose cleanly.
- The `WorktreeSandbox` adapter that enforces path confinement at the tool level.

## Build it

### Step 1 — Create `src/sandbox.py`

This module exposes one async function: `run_in_worktree`. It creates the worktree, runs the agent inside it, and returns the worktree path for the caller to inspect. It never commits, never merges — those decisions belong to the developer.

```python
# src/sandbox.py

"""Worktree sandbox: run the agent in an isolated git branch.

Usage:
    from sandbox import run_in_worktree

    worktree = await run_in_worktree(task="add type hints to tools.py")
    # Inspect: git -C worktree diff HEAD
    # Merge:   git merge agent/task-<id>
    # Discard: git worktree remove worktree --force
"""

import asyncio
import os
import subprocess
import uuid
from pathlib import Path


async def run_in_worktree(
    task: str,
    base_dir: str = ".",
    *,
    auto_cleanup_on_failure: bool = False,
) -> Path:
    """Create a git worktree, run the agent inside it, return the worktree path.

    The agent's working directory is changed to the worktree for the duration
    of the run. The caller is responsible for reviewing and removing the
    worktree when done.

    If auto_cleanup_on_failure is True, the worktree is removed when the
    agent makes no commits (partial run or error). Default: False — always
    keep the worktree so you can inspect partial results.
    """
    from agent import run_agent  # imported here to avoid circular imports

    run_id = uuid.uuid4().hex[:8]
    repo_root = Path(base_dir).resolve()
    worktree_path = repo_root.parent / f"agent-run-{run_id}"
    branch = f"agent/task-{run_id}"

    # Create a linked worktree on a new branch.
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
                check=False,
            )
            raise RuntimeError(
                f"Agent made no commits in worktree {worktree_path}; worktree removed."
            )

    return worktree_path
```

### Step 2 — Use it from `main.py`

Add an optional `--sandbox` flag so the user can opt in to worktree isolation:

```python
# main.py (updated)
import asyncio
import sys
from dotenv import load_dotenv


async def main() -> None:
    load_dotenv()
    args = sys.argv[1:]

    if args and args[0] == "--sandbox":
        task = " ".join(args[1:]) or input("Task: ")
        from sandbox import run_in_worktree
        worktree = await run_in_worktree(task)
        print(f"\n--- Agent finished in worktree: {worktree}")
        print(f"    Review: git -C {worktree} diff HEAD")
        print(f"    Merge:  git merge agent/task-{worktree.name.split('-')[-1]}")
        print(f"    Discard: git worktree remove {worktree} --force")
    else:
        task = " ".join(args) or input("Task: ")
        from agent import run_agent
        await run_agent(task)


if __name__ == "__main__":
    asyncio.run(main())
```

### Step 3 — Optional: the `WorktreeSandbox` path adapter

The worktree approach relies on the agent using relative paths (which resolve inside the worktree because `cwd` points there). If the model supplies an absolute path — a rare but possible failure mode — a file write will escape the worktree entirely.

The `WorktreeSandbox` adapter closes this at the tool level:

```python
# src/sandbox.py (addition)
from dataclasses import dataclass

@dataclass
class WorktreeSandbox:
    """Adapter that roots all relative file paths inside a worktree root.

    Pass an instance to write_file / edit_file to enforce path confinement:
        sandbox.resolve(args["path"])
    raises PermissionError if the resolved path is outside self.root.
    """
    root: Path

    def resolve(self, path: str) -> Path:
        resolved = (self.root / path).resolve()
        if not str(resolved).startswith(str(self.root)):
            raise PermissionError(
                f"Path escape attempt: {path!r} → {resolved} "
                f"(outside sandbox root {self.root})"
            )
        return resolved
```

To activate it, pass `cwd=str(sandbox.root)` in the `bash` tool's `subprocess.run` call and call `sandbox.resolve(path)` in `write_file` and `edit_file` before the write. This is a planned extension; the worktree approach alone (setting `cwd`) is sufficient for the common case.

### Container-based sandboxing

A git worktree provides filesystem isolation on the same machine. For process and network isolation — preventing the agent from reading your home directory, calling out to external endpoints, or consuming unbounded CPU — combine the worktree with a container:

```bash
# Build the agent image (see ../../operations/containerization.md).
docker build -t coding-agent .

# Mount the worktree path (not the main repo) inside the container.
WORKTREE=../agent-run-abc12345
docker run --rm \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -v "$WORKTREE:/workspace" \
  -w /workspace \
  --memory=512m --cpus=1.0 \
  coding-agent "add type hints to tools.py"
```

See [Containerization](../../operations/containerization.md) for the full setup and [Worktrees](../../architecture-patterns/worktrees.md) for a side-by-side comparison of the two isolation approaches.

| Approach | Filesystem isolation | Process isolation | Network isolation | Setup cost |
|---|---|---|---|---|
| No isolation | None | None | None | Zero |
| Worktree | Fresh branch on same machine | None | None | ~1 second |
| Container | Mount-scoped | Full | Configurable | 5–30 seconds |
| Worktree + container | Mount-scoped to worktree | Full | Configurable | 5–30 seconds |

## Test it

### Behavior (BDD)

Verify this layer as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Scenario: Agent writes land in a throwaway worktree, not the main working tree
  Given a git repository with a clean working tree
  And run_in_worktree is called with task "add a comment to tools.py"
  When the agent calls write_file or edit_file on "src/tools.py"
  Then the file is written inside the worktree directory (../agent-run-<id>/src/tools.py)
  And the file at src/tools.py in the main working tree is unchanged
  And run_in_worktree returns a Path pointing to the worktree
  And git -C <worktree> diff HEAD shows the agent's edit
```

Run this as an integration scenario with the [BDD framework](../../guides/bdd-integration-testing.md).

The scenario fails **before** this layer (the agent writes directly to the main working tree). After this layer it passes: the write lands in the worktree branch and the main tree is untouched.

## Run it

```bash
# Run with worktree isolation.
uv run main.py --sandbox "add a module docstring to src/tools.py"

# The agent reports the worktree path when it finishes:
# --- Agent finished in worktree: ../agent-run-a3f9c1b2
#     Review: git -C ../agent-run-a3f9c1b2 diff HEAD
#     Merge:  git merge agent/task-a3f9c1b2
#     Discard: git worktree remove ../agent-run-a3f9c1b2 --force

# Inspect the diff.
git -C ../agent-run-a3f9c1b2 diff HEAD

# If it looks good, merge.
git merge agent/task-a3f9c1b2

# Clean up.
git worktree remove ../agent-run-a3f9c1b2
git branch -d agent/task-a3f9c1b2
```

:::warning Bash side effects are not git-reversible
`git worktree remove` undoes file edits. It does not undo a `pip install`, a database migration, or an `npm publish` that the agent ran via `bash`. For tasks that might have external side effects, combine the worktree with a container so package installs go into the container layer, not your host.
:::

:::tip Architecture pattern
The worktree is a [Worktrees](../../architecture-patterns/worktrees.md) sandbox, modelled as a `SandboxPort` adapter under [Ports & Adapters](../../architecture-patterns/ports-and-adapters.md).
:::

## Recap

The worktree wrapper is a thin adapter around `run_agent`: create a branch, set `cwd`, run, return the path. Your main working tree is never touched. The diff is your review gate before anything merges.

Worktrees give filesystem isolation (branch-level). Containers give process and network isolation. They compose: mount the worktree inside a container for maximum safety.

The last layer adds structured diagnostics so you can observe what the agent is doing inside any of these environments — without adding noise to the model's output stream.

→ [Layer 12.5 — Logging & Settings](./5-logging-and-settings.md)
