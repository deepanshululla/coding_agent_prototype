Status: not started

# Phase 8 — System Prompt & CLI

## Goal

Add `src/prompts.py` with a `build_system_prompt` function that encodes the live working directory, today's date, and all seven tool names at call time; set `MAX_ITERATIONS = 30` in `src/agent.py` to bound the inner loop; and create `main.py` as the CLI entry point.

## Files changed

| File | Change |
|---|---|
| `src/prompts.py` | New file — `build_system_prompt(cwd, extra)` function that returns a formatted system prompt with live cwd, ISO date, tool list, and optional extra text |
| `src/agent.py` | Add `MAX_ITERATIONS = 30` constant; wire `build_system_prompt()` call at the top of `run_agent`; pass `system_prompt` into `stream_response` on every inner-loop iteration |
| `main.py` | New file at repo root — `load_dotenv`, `sys.path` injection for `src/`, task from `sys.argv` or `input()`, `asyncio.run(main())` entry point |
| `tests/test_prompts.py` | New file — 4 tests: cwd in output, today's date in output, all 7 tool names present, `extra` text appended |
| `tests/test_agent.py` | Add `test_max_iterations_is_set` — asserts `agent.MAX_ITERATIONS` is an int in range 1–100 |

## Order of operations

1. Write the failing tests in `tests/test_prompts.py` and the `test_max_iterations_is_set` test in `tests/test_agent.py`; confirm they fail.
2. Create `src/prompts.py` with `build_system_prompt` built per-run (not a module constant) using `os.getcwd()` and `date.today().isoformat()`.
3. Add `MAX_ITERATIONS = 30` to `src/agent.py` and wire `build_system_prompt()` into `run_agent` (called once at the top, passed into every `stream_response` call).
4. Create `main.py` at the repo root with `load_dotenv`, `sys.path.insert` for `src/`, task resolution from argv/stdin, and `asyncio.run(main())`.
5. Run `uv run pytest tests/ -v` and confirm all 17 tests (phases 6–8) pass.
6. Run the CLI end-to-end: `uv run main.py "list all .py files in the project"`.

## Verification

- [ ] Tests added/updated: `tests/test_prompts.py` (4 tests), `tests/test_agent.py` (`test_max_iterations_is_set`)
- [ ] CLI / service run: `uv run main.py "list all .py files in the project"`
- [ ] Interactive mode: `uv run main.py` (no args) prompts `Task:` and reads from stdin
- [ ] Full suite: `uv run pytest tests/ -v` shows 17 passed
- [ ] BDD acceptance criteria (run before/after the build as a red/green gate):

```gherkin
Feature: System prompt content and iteration cap
  build_system_prompt encodes live runtime values; MAX_ITERATIONS guarantees
  the inner loop terminates; the CLI resolves the task from argv or stdin.

  Scenario: the system prompt contains the cwd, today's date, and all 7 tool names
    Given build_system_prompt is called with a known cwd "/tmp/test-workspace"
    When the returned prompt string is inspected
    Then the prompt contains "/tmp/test-workspace"
    And the prompt contains today's date in ISO-8601 format
    And the prompt contains each of "read_file", "write_file", "edit_file", "bash", "grep", "find_files", "list_dir"

  Scenario: the loop halts at MAX_ITERATIONS when the model never stops
    Given a scripted model that always responds with a list_dir tool call and never emits finish_reason "stop"
    And MAX_ITERATIONS is patched to 3
    When run_agent runs
    Then at most 3 tool-call messages are dispatched
    And run_agent returns without hanging

  Scenario: the extra argument is appended verbatim to the system prompt
    Given build_system_prompt is called with extra="DEPLOY_ENV=staging"
    When the returned prompt string is inspected
    Then the prompt contains "DEPLOY_ENV=staging"
    And the extra text appears after the standard environment block

  Scenario: the CLI reads the task from argv and falls back to stdin
    Given main.py is invoked with sys.argv ["main.py", "list", "all", ".py", "files"]
    And a scripted model that returns a plain-text answer immediately
    When asyncio.run(main()) executes
    Then run_agent is called with task "list all .py files" (argv joined)
    Given main.py is invoked with sys.argv ["main.py"] and stdin contains "describe the repo"
    When asyncio.run(main()) executes
    Then run_agent is called with task "describe the repo" (stdin value)
```

## Notes / open questions

- `build_system_prompt` must be called per-run, not stored as a module-level constant — otherwise `cwd` and `today` would be stale after the first import.
- `main.py` lives at the repo root (not in `src/`) because it is the CLI entry point, not a library module.
- When `MAX_ITERATIONS` trips at 30, the loop exits silently with no error message to the model. This is intentional for v1; a future phase could append a timeout notice.
- Ensure `ANTHROPIC_API_KEY` (or another provider key) is set in `.env` before running the CLI; `load_dotenv()` in `main.py` picks it up.

---

**Tutorial build step 8 of 32** · ← [Phase 7 — Parallel Tool Execution](./phase-07-parallel-tools.md) · [Phase 9 — Testing the Agent](./phase-09-testing-the-agent.md) →
