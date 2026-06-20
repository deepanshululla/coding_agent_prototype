Status: done
Branch: step/phase-04-your-first-tool

# Phase 4 — Your First Tool

## Goal

Define a `read_file` tool (async function + OpenAI-style schema + registry entry) in a new `src/tools.py`, add a `ToolResult` dataclass in `src/types_.py`, and extend the `src/agent.py` inner loop to detect `finish_reason="tool_calls"`, dispatch the tool, and inject the result as a `role:"tool"` message before looping again.

## Files changed

| File | Change |
|---|---|
| `src/tools.py` | New file: `read_file` async function (wraps blocking I/O in `asyncio.to_thread`, returns error strings on failure), `TOOLS_SCHEMA` list, `TOOL_REGISTRY` dict |
| `src/types_.py` | New file: `ToolResult` dataclass with `tool_call_id`, `tool_name`, `content`, `is_error` |
| `src/agent.py` | Extend inner loop with Phases B–E: append assistant turn (with `tool_calls`), stop-check, parallel tool dispatch via `_execute_tools_parallel`, and `role:"tool"` message injection; add `_execute_tools_parallel` and `_execute_one_tool` helpers |
| `tests/test_agent.py` | Add `test_tool_call_then_stop` using `ScriptedLLM` with a two-turn scripted model (turn 1 requests `read_file`, turn 2 stops) |

## Order of operations

1. Create `src/types_.py` with the `ToolResult` dataclass.
2. Create `src/tools.py` with `read_file`, `TOOLS_SCHEMA`, and `TOOL_REGISTRY`.
3. Write the failing test `test_tool_call_then_stop` in `tests/test_agent.py`. Confirm it fails.
4. Update `src/agent.py`: import `TOOL_REGISTRY`, `ToolResult`, `json`; add `tool_acc` accumulation in Phase A; build `tool_calls` list after the stream; add Phase B (append assistant turn with optional `tool_calls`), Phase C (stop check), Phase D (parse and dispatch), Phase E (push `role:"tool"` messages); add `_execute_tools_parallel` and `_execute_one_tool`.
5. Run `test_tool_call_then_stop` — should pass. Run full suite for regressions.
6. Live run: `uv run main.py "read src/tools.py and tell me what tools are defined"`.

## Verification

- [ ] Tests added/updated: `tests/test_agent.py` (`test_tool_call_then_stop`)
- [ ] Run: `uv run pytest tests/test_agent.py::test_tool_call_then_stop -v` — expect `PASSED`
- [ ] Full suite: `uv run pytest tests/test_agent.py -v` — no regressions
- [ ] Live run produces `▸ read_file` line, executing log, and model summary
- [ ] BDD gate (red before, green after):

```gherkin
Feature: First tool call
  When the model emits finish_reason "tool_calls", run_agent executes the named
  tool, injects the result as a role:"tool" message addressed to the matching
  tool_call_id, and loops back to the model. The assistant turn that carries
  the tool call is appended to history before any tool result messages.

  Scenario: The model calls read_file and the file contents return as a role:"tool" message
    Given a file "notes.txt" containing "meeting at 3pm"
    And a scripted model whose turn 1 requests read_file on notes.txt with finish_reason "tool_calls"
    And turn 2 replies "The note says: meeting at 3pm." with finish_reason "stop"
    When run_agent("what's in notes.txt?") completes
    Then the history contains a role:"tool" message before the second assistant turn
    And that tool message content includes "meeting at 3pm"
    And the final assistant message content is "The note says: meeting at 3pm."

  Scenario: The assistant turn carrying a tool call has arguments as a JSON string, not a dict
    Given a scripted model that requests read_file with arguments '{"path": "/tmp/x.txt"}'
    And a follow-up turn that stops
    When run_agent completes
    Then messages[1] has role "assistant" and a "tool_calls" key
    And messages[1]["tool_calls"][0]["function"]["arguments"] is an instance of str
    And json.loads of that string succeeds and contains the key "path"

  Scenario: The tool result message is addressed to the correct tool_call_id
    Given a scripted model that requests read_file with id "call_abc" and finish_reason "tool_calls"
    And a follow-up turn that stops
    When run_agent completes
    Then the role:"tool" message in history has tool_call_id equal to "call_abc"
    And no other tool_call_id appears in the tool messages

  Scenario: A read of a missing file returns an error result and the loop continues
    Given no file exists at the path the scripted model will request
    And a scripted model whose turn 1 requests read_file on that missing path
    And turn 2 replies "The file does not exist; I cannot proceed." with finish_reason "stop"
    When run_agent("read missing.txt") completes
    Then the role:"tool" message content contains "error" or "not found" (case-insensitive)
    And the loop did not crash or raise an exception
    And the history contains exactly 2 assistant turns (the tool-call turn and the recovery turn)
```

## Notes / open questions

- Tool-calling through `claude -p` is a simplified bridge — the CLI runs its own loop and does not receive `TOOLS_SCHEMA` via the native function-calling protocol. Full multi-provider tool calling arrives with LiteLLM in Phase 11. Tests exercise the dispatch logic via `ScriptedLLM` regardless.
- `arguments` must stay a JSON string in message history (never convert to dict); providers round-trip the verbatim string and break if a dict is stored instead.
- The assistant turn appended in Phase B **must** include `tool_calls` even if `content` is empty — omitting it breaks provider conversation validation.
- Phase 4 assumes arguments arrive whole in one chunk. Phase 5 handles the streaming split case.
- `read_file` returns error strings rather than raising, so the model can read the error and try a corrective action.

---

**Tutorial build step 4 of 32** · ← [Phase 3 — Streaming Responses](./phase-03-streaming.md) · [Phase 5 — Streaming Tool Calls](./phase-05-streaming-tool-calls.md) →
