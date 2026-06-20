---
sidebar_position: 11
title: Worktrees
description: Isolate the agent's edits in a git worktree so a bad run can't corrupt your working tree, and you review the diff before merging anything.
---

# Worktrees

The agent's `write_file`, `edit_file`, and `bash` tools operate on the real filesystem at whatever `cwd` the process inherited. If the agent makes a mistake — overwrites a file it shouldn't have touched, runs a destructive command, or gets halfway through a refactor before hitting an error — your working tree is damaged. You can recover with `git checkout`, but only if you committed first.

A worktree sidesteps this entirely. The agent works in a throwaway branch; you review the diff and merge only what looks good.

:::note Design guidance
This page describes a recommended isolation pattern, not something the shipped core implements automatically. The `bash` and file tools in `src/tools.py` operate on whatever `cwd` is set at process start. Worktrees are the lightweight filesystem-level enforcement layer you add around that.
:::

## The problem

The `bash` tool in `src/tools.py` runs with `shell=True` against the process's working directory:

```python
proc = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=BASH_TIMEOUT)
```

`write_file` and `edit_file` accept any `path` argument the model supplies and write to it directly via `Path(path).write_text(content)`. There is no sandboxing built into these tools — they trust the path and the command.

That's intentional: the tools are meant to be fast and composable. The isolation is your responsibility, and it belongs outside the tools, not inside them.

Without isolation, three common failure modes bite you:

1. **Partial edits.** The agent refactors three files successfully, then errors on the fourth. Now your working tree has a mix of old and new code that may not compile.
2. **Collateral writes.** A confident-but-wrong model uses an absolute path and overwrites a file outside the project it was supposed to touch.
3. **Dirty working tree pollution.** You were mid-feature when you ran the agent. Its changes interleave with yours, making `git diff` noisy and `git stash` awkward.

## The pattern

Create a dedicated `git worktree` for each agent run. The agent works exclusively in that worktree; your main working tree is untouched.

```
your repo (main working tree)
  ├── .git/
  ├── src/
  └── ...  ← you work here, unchanged

../agent-run-<id>/  ← git worktree (a linked checkout)
  ├── src/          ← agent edits here
  └── ...
```

When the run finishes:

- **Good run:** review the diff, merge or cherry-pick into your branch.
- **Bad run:** delete the worktree — no recovery needed, your tree was never touched.

Frame this as a `SandboxPort` — an adapter in the [Ports & Adapters](./ports-and-adapters.md) sense — that the file and bash tools run inside. The core agent loop doesn't change; only the working directory it inherits changes.

## In this project

The file tools (`write_file`, `edit_file`, `read_file`) use `Path(path)` which resolves relative to `cwd`. The `bash` tool inherits the process environment. Neither tool needs to change. You set `cwd` before the agent starts.

### Creating the worktree

```bash
# Generate a run ID so multiple concurrent runs don't collide.
RUN_ID=$(python -c "import uuid; print(uuid.uuid4().hex[:8])")

# Create a new branch and a linked worktree in one command.
git worktree add ../agent-run-$RUN_ID -b agent/task-$RUN_ID

echo "Worktree ready at: ../agent-run-$RUN_ID"
```

`git worktree add` creates a directory that shares the same `.git` object store as your main repo, but has its own `HEAD`, index, and working files. It costs almost nothing — just a copy of the checked-out files.

### Pointing the agent at the worktree

```python
import asyncio
import os
import subprocess
import uuid
from pathlib import Path

from agent import run_agent

async def run_in_worktree(task: str, base_dir: str = ".") -> Path:
    """
    Create a worktree, run the agent inside it, return the worktree path.
    The caller reviews the diff and decides whether to merge.
    """
    run_id = uuid.uuid4().hex[:8]
    repo_root = Path(base_dir).resolve()
    worktree_path = repo_root.parent / f"agent-run-{run_id}"
    branch = f"agent/task-{run_id}"

    # Create the worktree on a fresh branch.
    subprocess.run(
        ["git", "worktree", "add", str(worktree_path), "-b", branch],
        cwd=repo_root,
        check=True,
    )

    # Switch cwd to the worktree before running the agent.
    original_cwd = os.getcwd()
    os.chdir(worktree_path)
    try:
        await run_agent(task)
    finally:
        os.chdir(original_cwd)

    return worktree_path
```

### Review and merge

After the agent finishes, inspect what it did:

```bash
WORKTREE=../agent-run-abc12345
BRANCH=agent/task-abc12345

# See every file the agent touched.
git -C "$WORKTREE" diff HEAD

# Or compare against your current branch in the main tree.
git diff main..$BRANCH

# If it looks good, merge or cherry-pick into your branch.
git merge --no-ff $BRANCH -m "Apply agent changes: <task description>"

# Or, if you only want some of the commits:
git cherry-pick <commit-sha>
```

### Cleanup

```bash
# Remove the worktree directory and deregister it from git.
git worktree remove ../agent-run-abc12345

# The branch is still there if you merged; delete it when done.
git branch -d agent/task-abc12345
```

You can also automate cleanup after a failed run:

```python
import shutil

async def run_in_worktree_safe(task: str, base_dir: str = ".") -> Path | None:
    worktree_path = await run_in_worktree(task, base_dir)
    # Check whether the agent produced any commits.
    result = subprocess.run(
        ["git", "log", "HEAD", "--oneline", "-1"],
        cwd=worktree_path, capture_output=True, text=True,
    )
    if result.returncode != 0:
        # No commits — agent failed or made no progress. Clean up.
        subprocess.run(["git", "worktree", "remove", "--force", str(worktree_path)])
        return None
    return worktree_path
```

### SandboxPort: the adapter view

In the [Ports & Adapters](./ports-and-adapters.md) model, the file system and shell are external resources the agent reaches through adapters. A `SandboxPort` is an adapter that confines those calls to a worktree:

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass
class WorktreeSandbox:
    """Adapter that roots all relative file paths inside a worktree."""
    root: Path

    def resolve(self, path: str) -> Path:
        """Ensure path stays inside the sandbox root."""
        resolved = (self.root / path).resolve()
        if not str(resolved).startswith(str(self.root)):
            raise PermissionError(f"Path escape attempt: {path!r} → {resolved}")
        return resolved
```

The `read_file`, `write_file`, and `edit_file` tools would accept an optional `sandbox: WorktreeSandbox` argument and call `sandbox.resolve(path)` before any I/O. The `bash` tool would set `cwd=str(sandbox.root)` in its `subprocess.run` call. The core logic is unchanged; the sandbox is a thin wrapper at the boundary.

## Comparing isolation approaches

| Approach | Filesystem isolation | Process isolation | Network isolation | Setup cost |
|---|---|---|---|---|
| **No isolation** | None — whole host | None | None | Zero |
| **Worktree** | Cheap FS branch; same machine | None — same process | None | ~1 second |
| **Container** | Mount-scoped | Full — separate process tree | Configurable with `--network` | 5–30 seconds |
| **Worktree + container** | Mount-scoped to worktree path | Full | Configurable | 5–30 seconds |

Worktrees and containers solve different problems and compose cleanly: run the agent in a container (for process and network isolation), but mount the container's working directory at a worktree path (for cheap branch-level FS isolation with easy diff/merge). See [Containerization](../operations/containerization.md) for the container half of that setup.

The container page's key warning applies here too: the mounted directory is still writable. A worktree limits the blast radius to one branch; it doesn't protect against the agent intentionally or accidentally deleting worktree files. Always run in a git repository so `git diff` and `git checkout` are available.

## Trade-offs

**What worktrees give you**

- Your main working tree is never touched during an agent run — no matter what the agent does.
- Every agent run is a git branch. Diff, log, rebase, cherry-pick — all the normal git tools work on the agent's output.
- Multiple agent runs can run concurrently on separate branches without interfering.
- Setup and teardown are fast: a worktree add/remove is a filesystem copy plus a couple of git index operations.

**What worktrees do not give you**

- **Process isolation.** The agent runs in the same process (or at least the same OS user) as you. A `bash` command can still read your home directory, call out to the network, or exhaust CPU. For that, combine with a container.
- **Path escape protection without the adapter.** If the model supplies an absolute path outside the worktree, the bare file tools will follow it. The `WorktreeSandbox` adapter above closes this; without it, you rely on the model not doing that.
- **Undo for bash side effects.** `git worktree remove` undoes file edits. It does not undo a `pip install`, a database migration, or an `npm publish` that the agent ran via `bash`.

:::warning Bash side effects are not git-reversible
If the agent's `bash` calls modify state outside the worktree — installed packages, running services, external APIs — a `git worktree remove` won't undo those. For tasks that might have external side effects, combine worktrees with a container (so `pip install` goes into the container layer, not your host) or use the [policy engine](./policy-engine.md) to block `bash` calls that match risky patterns.
:::

## Related

- [Ports & Adapters](./ports-and-adapters.md) — the `SandboxPort` adapter fits into the hexagonal model; the file and bash tools become adapters wrapping a configurable sandbox
- [Policy Engine](./policy-engine.md) — complements the worktree by blocking dangerous `bash` patterns before they execute, not just isolating their filesystem effects
- [Containerization](../operations/containerization.md) — process- and network-level isolation that composes with worktrees; use both for maximum safety
- [Security Model](../operations/security.md) — the full threat model and how worktrees fit into the layered defense
