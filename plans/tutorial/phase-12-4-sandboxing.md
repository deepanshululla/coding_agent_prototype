Status: not started

# Phase 12.4 — Sandboxing

## Goal

Wrap `run_agent` in a git worktree so every agent run works on an isolated branch, leaving the main working tree untouched; return the worktree path so the developer can `git diff`, merge, or discard the result.

## Files changed

| File | Change |
|---|---|
| `src/sandbox.py` | New module: `run_in_worktree(task, base_dir, auto_cleanup_on_failure)` async function; `WorktreeSandbox` dataclass with `resolve(path)` for optional path-confinement enforcement |
| `main.py` | Add `--sandbox` flag: when present, delegate to `run_in_worktree` and print the post-run review/merge/discard instructions; default path unchanged |
| `tests/test_sandbox.py` | Integration test: create a real git worktree via `run_in_worktree`, assert the main tree is unmodified, assert the worktree path exists and contains the agent's write |

## Order of operations

1. Create `src/sandbox.py` with `run_in_worktree`: generate a `uuid`-based run ID, build the worktree path as `repo_root.parent / f"agent-run-{run_id}"`, run `git worktree add -b agent/task-{run_id}`, `os.chdir` into it, call `run_agent(task)`, `os.chdir` back in `finally`, return the worktree path.
2. Add the optional `auto_cleanup_on_failure` branch: check `git log HEAD --oneline -1` in the worktree; if empty, run `git worktree remove --force` and raise `RuntimeError`.
3. Add `WorktreeSandbox` dataclass with `resolve(path)` that raises `PermissionError` on paths escaping `self.root`. Mark this as a planned extension, activated by passing `cwd=str(sandbox.root)` to `bash` and calling `sandbox.resolve()` in `write_file`/`edit_file`.
4. Update `main.py`: parse `--sandbox` from `sys.argv`; when present, import and call `run_in_worktree`; print the four-line post-run hint (Review / Merge / Discard); otherwise call `run_agent` as before.
5. Write `tests/test_sandbox.py`: requires a git repo fixture; call `run_in_worktree` with a trivial task; assert the worktree path is returned, is a directory, and the main tree's target file is unchanged.
6. Run BDD scenario (red → green).
7. Full CLI smoke-test with `uv run main.py --sandbox "add a module docstring to src/tools.py"`.

## Verification

- [ ] Tests added/updated: `tests/test_sandbox.py`
- [ ] Unit/integration tests pass: `uv run pytest tests/test_sandbox.py -v`
- [ ] CLI smoke: `uv run main.py --sandbox "add a module docstring to src/tools.py"`
  - Expected: agent prints `--- Agent finished in worktree: ../agent-run-<id>` with Review/Merge/Discard lines
- [ ] Manual verify main tree untouched: `git status` in the main repo shows no modifications after the sandboxed run
- [ ] Manual verify diff in worktree: `git -C ../agent-run-<id> diff HEAD` shows the agent's edit
- [ ] BDD scenario passes (green):

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

## Notes / open questions

- `os.chdir` is process-global; this works for the common single-task case but is not safe for concurrent `run_in_worktree` calls in the same process. If concurrent runs are needed later, pass an explicit `cwd` parameter through `run_agent` and into `subprocess.run` calls in `tools.py` rather than using `os.chdir`.
- `WorktreeSandbox.resolve()` is a planned extension (Step 3). It is included in `src/sandbox.py` but not wired into `write_file`/`edit_file` until a later follow-up. Absolute-path escapes are an edge case that the model rarely triggers in practice.
- `bash` side effects (e.g. `pip install`, `npm publish`) are not undone by `git worktree remove`. For tasks with external side effects, the tutorial recommends combining the worktree with a container (see `website/docs/operations/containerization.md`).
- Cleanup after a successful run is the developer's responsibility: `git worktree remove <path>` + `git branch -d agent/task-<id>`. Consider adding a `--cleanup` flag to `main.py` in a later layer.

---

**Tutorial build step 19 of 32** · ← [Phase 12.3 — Permissions & Modes](./phase-12-3-permissions-and-modes.md) · [Phase 12.5 — Logging & Settings](./phase-12-5-logging-and-settings.md) →
