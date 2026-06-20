Status: done
Branch: step/phase-13-2-prompt-templates-and-hooks

# Phase 13.2 — Prompt Templates & Hooks

## Goal

Add per-session instruction injection via `AGENT_SESSION_CONTEXT` env var and wire `beforeToolCall` / `afterToolCall` hook points into `_execute_one_tool` in `src/agent.py`, plus provide ready-to-use implementations in a new `src/hooks.py`.

## Files changed

| File | Change |
|---|---|
| `src/agent.py` | Add optional `before_tool_call` and `after_tool_call` params to `_execute_one_tool`, `_execute_tools_parallel`, and `run_agent`; insert hook call sites before/after `fn(**args)` |
| `src/hooks.py` | New module — `log_after_tool_call` (JSONL logger) and `confirm_before_tool_call` (async permission gate) |
| `main.py` | Read `AGENT_SESSION_CONTEXT`; compose it with project instructions into `extra`; wire `log_after_tool_call` as `after_tool_call` to `run_agent` |
| `tests/test_hooks.py` | New tests — `beforeToolCall` fires and receives correct args; returning `False` denies tool; `afterToolCall` receives result and can transform it; log file is written |

## Order of operations

1. Write a failing test that calls `_execute_one_tool` with a `before_tool_call` spy and asserts the spy was awaited. Confirm failure (`TypeError`: unexpected keyword argument).
2. Update `_execute_one_tool` signature to accept `before_tool_call=None` and `after_tool_call=None`; add call sites; thread params through `_execute_tools_parallel`. Run test — green.
3. Write a test that `before_tool_call` returning `False` causes `_execute_one_tool` to return an error `ToolResult` without calling the tool. Run test.
4. Write a test that `after_tool_call` receives `(name, args, result)` and its return value replaces the result. Run test.
5. Create `src/hooks.py` with `log_after_tool_call` and `confirm_before_tool_call`. Write a test that `log_after_tool_call` writes a JSONL entry to `LOG_PATH`.
6. Update `main.py` to compose `AGENT_SESSION_CONTEXT` into `extra` and pass `log_after_tool_call` to `run_agent`. Run `uv run pytest -q`.

## Verification

- [ ] Tests added: `tests/test_hooks.py`
- [ ] Full suite: `uv run pytest -q` — all prior tests pass (hooks default to `None`, no signature break)
- [ ] Per-session injection: `AGENT_SESSION_CONTEXT="This session: focus on performance bottlenecks." uv run main.py "profile the agent loop"` — override text appears in prompt
- [ ] Tool logging: run agent on any task, then inspect `.agent-tool-log.jsonl` for entries
- [ ] Log command: `uv run python -c "import asyncio; from src.agent import run_agent; from src.prompts import build_system_prompt; from src.hooks import log_after_tool_call; asyncio.run(run_agent('list the src directory', system_prompt=build_system_prompt(), after_tool_call=log_after_tool_call))"` then `cat .agent-tool-log.jsonl`

### Acceptance (BDD)

```gherkin
Scenario: Injected template appears in the prompt AND beforeToolCall hook fires
  Given AGENT_SESSION_CONTEXT is set to "Output responses in JSON only"
  And a beforeToolCall hook that records each tool name in a list
  When the agent is initialized and processes a task that triggers a read_file call
  Then the system prompt contains "Output responses in JSON only"
  And the beforeToolCall hook's recorded list contains "read_file"
  And the tool result is returned normally (hook returned True)
```

## Notes / open questions

- Parallel tool calls: `asyncio.gather` fires both hooks concurrently. If `confirm_before_tool_call` is used, two `input()` prompts may appear simultaneously. Consider serializing dispatch when an interactive `before_tool_call` is set.
- `after_tool_call` return value replaces `result` — hook authors must return the result string even if unmodified.
- The JSONL log path (`LOG_PATH`) is hardcoded to `.agent-tool-log.jsonl` in the cwd; make it configurable via env var if needed later.

---

**Tutorial build step 22 of 32** · ← [Phase 13.1 — Project Instructions (AGENTS.md)](./phase-13-1-project-instructions.md) · [Phase 13.3 — Skills](./phase-13-3-skills.md) →
