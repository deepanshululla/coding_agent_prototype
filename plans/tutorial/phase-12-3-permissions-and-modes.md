Status: done
Branch: step/phase-12-3-permissions-and-modes

# Phase 12.3 — Permissions & Modes

## Goal

Introduce a composable `PolicyEngine` and `AGENT_PERMISSION_MODE` environment variable so the same agent binary can operate read-only, prompt before dangerous actions (`ask`), or execute autonomously within the allowlist (`auto`) without any code changes between runs.

## Files changed

| File | Change |
|---|---|
| `src/policy.py` | New module: `Decision` dataclass; `Rule` ABC; `ReadOnlyRule`, `CommandAllowlistRule`, `PathRestrictionRule` concrete rules; `PolicyEngine` with `from_env()` factory |
| `src/agent.py` | Replace Layer 12.2 direct `check_command` gate with `_policy.check(name, args)`; add `_prompt_lock` and `_prompt_user()` helper; import `PolicyEngine`, `asyncio` |
| `tests/test_policy.py` | Unit tests for each rule in isolation and for `PolicyEngine.from_env()` under each mode; mock stdin for `ask` mode approval/denial |

## Order of operations

1. Create `src/policy.py` with `Decision`, `Rule` (ABC), and the three concrete rules: `ReadOnlyRule`, `CommandAllowlistRule` (delegates to `allowlist.check_command`), `PathRestrictionRule`.
2. Implement `PolicyEngine.__init__` (rules list + default outcome) and `PolicyEngine.check()` (first non-None rule wins, else default).
3. Implement `PolicyEngine.from_env()`: `read-only` → `[ReadOnlyRule()]` + default `deny`; `auto` → `[CommandAllowlistRule(), PathRestrictionRule()]` + default `deny`; `ask` (default) → same rules + default `ask`.
4. Write `tests/test_policy.py`: test each rule in isolation; test `from_env()` for all three modes; mock `input()` for `ask` path.
5. In `src/agent.py`: remove the direct `check_command` import and gate; add `_policy = PolicyEngine.from_env()` module singleton; add `_prompt_lock = asyncio.Lock()`; add `_prompt_user()` async helper; replace old gate with the three-branch policy check (`deny` → error result, `ask` → prompt, `allow` → dispatch).
6. Run BDD scenario (red → green).
7. Smoke-test all three modes with the CLI commands in Run it.

## Verification

- [ ] Tests added/updated: `tests/test_policy.py`
- [ ] Unit tests pass: `uv run pytest tests/test_policy.py -v`
- [ ] CLI smoke — read-only denies writes: `AGENT_PERMISSION_MODE=read-only uv run main.py "show me what tools.py contains"`
- [ ] CLI smoke — ask mode prompts: `AGENT_PERMISSION_MODE=ask uv run main.py "add a module docstring to tools.py"` — must show `[PERMISSION REQUEST]` and `Allow? [y/N]`
- [ ] CLI smoke — auto mode runs within allowlist: `AGENT_PERMISSION_MODE=auto AGENT_BASH_ALLOWLIST="pytest,git,python" uv run main.py "Run the test suite and report failures"`
- [ ] BDD scenario passes (green):

```gherkin
Scenario: Permission modes gate write and execute tools correctly
  Given the agent with the PolicyEngine installed in _execute_one_tool

  When AGENT_PERMISSION_MODE=read-only and the agent requests write_file
  Then _execute_one_tool returns ToolResult(is_error=True)
  And the reason contains "read-only mode is active"
  And the write_file function is never called

  When AGENT_PERMISSION_MODE=ask and the agent requests write_file
  And the user types "n" at the approval prompt
  Then _execute_one_tool returns ToolResult(is_error=True)
  And the reason contains "not approved"
  And the write_file function is never called
```

## Notes / open questions

- `_prompt_user()` uses `asyncio.Lock` to serialise concurrent prompts from parallel tool calls in the same turn. Without the lock, two `input()` calls interleave on the terminal and are impossible to answer correctly.
- `PathRestrictionRule` uses `pathlib.Path.is_relative_to()` (Python 3.9+). Verify the project's `pyproject.toml` requires 3.9+; if not, fall back to `str(resolved).startswith(str(self.root))`.
- `PolicyEngine` is a module-level singleton (`_policy = PolicyEngine.from_env()`) so `AGENT_PERMISSION_MODE` is read once at startup, not per call. Tests that need to vary the mode should instantiate `PolicyEngine` directly rather than relying on the env var.
- `CommandAllowlistRule` in Layer 12.3 subsumes the direct `check_command` gate added in Layer 12.2. After this layer, `src/agent.py` should no longer import `check_command` directly.

---

**Tutorial build step 18 of 32** · ← [Phase 12.2 — Command Allowlist](./phase-12-2-command-allowlist.md) · [Phase 12.4 — Sandboxing](./phase-12-4-sandboxing.md) →
