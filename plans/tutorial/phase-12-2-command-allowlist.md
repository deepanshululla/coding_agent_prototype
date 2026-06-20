Status: not started

# Phase 12.2 — Command Allowlist

## Goal

Install a default-deny command allowlist gate in `_execute_one_tool` so only explicitly permitted programs can run via `bash`, closing the shell-metacharacter chaining trap before program-name checking begins.

## Files changed

| File | Change |
|---|---|
| `src/allowlist.py` | New module: `check_command(command) → Verdict`; `SHELL_METACHARACTERS`, `DEFAULT_ALLOWED_PROGRAMS`, `PROGRAM_ARG_RULES`; `_load_allowlist()` reads `AGENT_BASH_ALLOWLIST` env var |
| `src/agent.py` | Add `from allowlist import check_command`; insert allowlist gate in `_execute_one_tool` at the `beforeToolCall` position (after args extraction, before registry lookup) |
| `tests/test_allowlist.py` | Seven unit tests for `check_command`: allowed program, denied program, command chaining, command substitution, pipe, unlisted git subcommand, listed git subcommand |

## Order of operations

1. Create `src/allowlist.py` with the `Verdict` dataclass, `SHELL_METACHARACTERS` tuple, `DEFAULT_ALLOWED_PROGRAMS` set, `PROGRAM_ARG_RULES` dict, `_load_allowlist()`, and `check_command()`. No imports from `agent.py` or `tools.py`.
2. Write `tests/test_allowlist.py` with all seven unit tests. Run: `uv run pytest tests/test_allowlist.py -v` — all must pass.
3. Add `from allowlist import check_command` to `src/agent.py`.
4. Insert the allowlist gate block inside `_execute_one_tool`, guarded by `if name == "bash"`, returning `ToolResult(..., is_error=True)` on denial.
5. Run the BDD integration scenario (red → green): before the gate the scenario fails; after the gate it passes.
6. Smoke-test with the two CLI commands in Run it.

## Verification

- [ ] Tests added/updated: `tests/test_allowlist.py`
- [ ] Unit tests pass: `uv run pytest tests/test_allowlist.py -v` (7/7)
- [ ] CLI smoke — allowed command runs: `uv run main.py "list the files in the current directory"`
- [ ] CLI smoke — disallowed command refused: `uv run main.py "run: rm -rf __pycache__"`
  - Expected: agent sees `Error: 'rm' is not an allowed command...` and adapts.
- [ ] BDD scenario passes (green):

```gherkin
Scenario: Disallowed command is refused before execution
  Given the agent with the command allowlist gate installed in _execute_one_tool
  And "rm" is not in the allowed programs list
  When the agent requests bash with command "rm -rf /"
  Then _execute_one_tool returns a ToolResult with is_error=True
  And the ToolResult content contains "not an allowed command"
  And the bash tool function is never called
```

## Notes / open questions

- `PROGRAM_ARG_RULES` for `git` restricts to `{status, log, diff, show, branch, stash}` — `git push`, `git commit`, and `git checkout` are blocked by default. This is intentional but may surprise users doing write-heavy workflows; they can add programs via `AGENT_BASH_ALLOWLIST`.
- The gate belongs in `_execute_one_tool` (not inside the `bash` function itself) so `agent.py` owns the policy and `tools.py` stays a pure capability registry. This position is described as `beforeToolCall` in the tutorial.
- Compound commands like `cd build && make` are also blocked by the metacharacter check; document this trade-off in the module docstring (already provided in the page's code sample).
- `_load_allowlist()` is called on every `check_command` invocation, which re-reads the env var each time. This is intentional for testability; if performance becomes a concern later, cache it as a module-level singleton.

---

**Tutorial build step 17 of 32** · ← [Phase 12.1 — The Security Model](./phase-12-1-security-model.md) · [Phase 12.3 — Permissions & Modes](./phase-12-3-permissions-and-modes.md) →
