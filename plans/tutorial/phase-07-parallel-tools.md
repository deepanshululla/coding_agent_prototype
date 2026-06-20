Status: done
Branch: step/phase-07-parallel-tools

# Phase 7 — Parallel Tool Execution

## Goal

Add `_execute_tools_parallel` and `_execute_one_tool` to `src/agent.py` so all tool calls from a single model turn run concurrently via `asyncio.gather`, with unknown-tool errors and unexpected exceptions both returned as `ToolResult` rather than raised.

## Files changed

| File | Change |
|---|---|
| `src/agent.py` | Add `_execute_tools_parallel` and `_execute_one_tool` below `run_agent`; update Phase D of the inner loop to call `_execute_tools_parallel` instead of sequential dispatch |
| `tests/test_agent.py` | Add `test_parallel_dispatch_two_tools` and `test_unknown_tool_returns_error_not_raise` |

## Order of operations

1. Write the two failing tests in `tests/test_agent.py` and confirm they fail with `AttributeError` (function doesn't exist yet).
2. Add `_execute_one_tool` to `src/agent.py`: look up the tool name in `TOOL_REGISTRY`, return a `ToolResult(is_error=True)` for unknown names, `await fn(**args)`, and wrap the whole call in a `try/except` backstop that also returns `ToolResult(is_error=True)` rather than raising.
3. Add `_execute_tools_parallel` to `src/agent.py`: a single `asyncio.gather` over `_execute_one_tool` for each call in the batch.
4. Wire the Phase D block in the inner loop to call `results = await _execute_tools_parallel(parsed_calls)`.
5. Run `uv run pytest tests/test_agent.py -v` and confirm both new tests pass.

## Verification

- [ ] Tests added/updated: `tests/test_agent.py` (2 new tests pass)
- [ ] CLI / service run: `uv run main.py "Show me the first 5 lines of src/agent.py and the first 5 lines of src/tools.py"`
- [ ] Observe that both `▸ read_file` markers appear before either `[executing ...]` line when the model batches the calls in one turn
- [ ] BDD acceptance criteria (run before/after the build as a red/green gate):

```gherkin
Feature: Parallel tool execution
  When the model emits multiple tool calls in a single streaming turn, the agent
  executes them concurrently and returns all results before the next model call.
  Order, error isolation, and unknown-name handling are all preserved.

  Scenario: two tool calls in one turn both return addressed to their correct ids
    Given files "a.txt" containing "content-alpha" and "b.txt" containing "content-beta"
    And a scripted model that requests read_file on both files in a single turn
    And the scripted model will then return a plain-text final answer
    When run_agent runs
    Then exactly 2 role:"tool" messages appear in the message history before the next assistant turn
    And the tool result with tool_call_id "c0" contains "content-alpha"
    And the tool result with tool_call_id "c1" contains "content-beta"

  Scenario: results preserve input order even if the slower tool was requested first
    Given files "slow.txt" and "fast.txt" exist
    And a scripted model that requests read_file on "slow.txt" at index 0 and read_file on "fast.txt" at index 1 in one turn
    And the scripted model will then return a plain-text final answer
    When run_agent runs
    Then the tool result messages appear in the history in request order: index-0 result before index-1 result

  Scenario: one tool erroring does not prevent the other tool's result from returning
    Given a scripted model that requests read_file on a missing path at index 0 and read_file on an existing "ok.txt" at index 1 in one turn
    And the scripted model will then return a plain-text final answer
    When run_agent runs
    Then the tool result for the missing path contains "Error"
    And the tool result for "ok.txt" contains the file's content
    And both role:"tool" messages are present (neither is missing due to the error)

  Scenario: an unknown tool name yields an error result not a crash
    Given a scripted model that requests an unknown tool "no_such_tool" in one turn
    And the scripted model will then return a plain-text final answer
    When run_agent runs
    Then the tool result message contains "Unknown tool"
    And run_agent completes without raising a Python exception
    And the final answer is the scripted plain-text response
```

## Notes / open questions

- `asyncio.gather` guarantees that `results[i]` corresponds to `tool_calls[i]` regardless of completion order — this ordering is important for providers that match results to requests by position.
- The fallback `try/except` in `_execute_one_tool` exists even though Phase 6 tools promise never to raise. It guards against bugs in future tools or malformed arguments that bypass schema validation.
- Do not add `asyncio.to_thread` here — the blocking-I/O wrapping is already inside each tool function from Phase 6. `_execute_one_tool` just `await`s the async tool function.

---

**Tutorial build step 7 of 32** · ← [Phase 6 — A Toolbox](./phase-06-a-toolbox.md) · [Phase 8 — System Prompt & CLI](./phase-08-system-prompt-and-cli.md) →
