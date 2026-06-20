Status: done
Branch: step/phase-05-streaming-tool-calls

# Phase 5 — Streaming Tool Calls

## Goal

Fix the inner loop's tool-call accumulation so that argument fragments arriving across multiple chunks are buffered by `index` into `arguments_buf` and `json.loads` is called exactly once after the stream ends — handling the realistic streaming case that Phase 4 assumed away.

## Files changed

| File | Change |
|---|---|
| `src/agent.py` | Replace Phase 4's simplified fragment handling with the full `tool_acc: dict[int, dict]` accumulation pattern: guard `id` and `name` assignment with `if tc_chunk.id:` / `if fn and fn.name:`, concatenate `fn.arguments` into `arguments_buf`, move `json.loads` to Phase D after the stream |
| `tests/test_agent.py` | Add `test_streaming_tool_call_split_arguments`: two-chunk turn where path JSON is split across chunks; asserts full string is stored and file content lands in the `role:"tool"` message |

## Order of operations

1. Write the failing test `test_streaming_tool_call_split_arguments` in `tests/test_agent.py`. Confirm it fails with `JSONDecodeError` or an assertion error.
2. Update the `async for chunk in stream_response(...)` block in `src/agent.py`:
   - Use `tool_acc.setdefault(idx, {"id": "", "name": "", "arguments_buf": ""})` per `tc_chunk.index`.
   - Guard `slot["id"] = tc_chunk.id` behind `if tc_chunk.id:`.
   - Guard `slot["name"] = fn.name` behind `if fn and fn.name:`.
   - Concatenate `slot["arguments_buf"] += fn.arguments` (not replace).
3. Move `json.loads(tc["function"]["arguments"] or "{}")` from the stream loop into Phase D (after the `async for` ends).
4. Run `test_streaming_tool_call_split_arguments` — should pass. Run full suite for regressions.
5. Optionally add `print(repr(fn.arguments))` inside the arguments block and run the live task to observe raw fragments.

## Verification

- [ ] Tests added/updated: `tests/test_agent.py` (`test_streaming_tool_call_split_arguments`)
- [ ] Run: `uv run pytest tests/test_agent.py::test_streaming_tool_call_split_arguments -v` — expect `PASSED`
- [ ] Full suite: `uv run pytest tests/test_agent.py -v` — no regressions
- [ ] Live run: `uv run main.py "read src/agent.py and summarize what the inner loop does"` — no JSON errors, model summary appears
- [ ] BDD gate (red before, green after):

```gherkin
Feature: Streaming tool-call accumulation
  Tool-call arguments arrive as partial JSON fragments across multiple chunks,
  identified by index. The agent buffers each index's fragments and calls
  json.loads exactly once after the stream ends — never mid-stream. Metadata
  (id, name) appears only on the first fragment per index and must not be
  overwritten by later None values.

  Scenario: Arguments split across two chunks parse into a valid dict after the stream
    Given a file "data.txt" containing "streaming works"
    And a scripted model whose turn 1 yields:
      | chunk 1 | index 0, id "call_split", name "read_file", arguments first half of path JSON |
      | chunk 2 | index 0, id None, name None, arguments second half of path JSON               |
      | chunk 3 | finish_reason "tool_calls"                                                    |
    And turn 2 replies "File content received." with finish_reason "stop"
    When run_agent("read the data file") completes
    Then messages[1]["tool_calls"][0]["function"]["arguments"] is a str
    And json.loads of that string produces {"path": "<full path to data.txt>"}
    And the role:"tool" message content contains "streaming works"

  Scenario: id and name from the first fragment are not overwritten by later None values
    Given a scripted model whose turn 1 sends three argument fragments for index 0
    And only the first fragment carries id "call_id_1" and name "read_file"
    And the subsequent fragments carry id None and name None
    When run_agent processes the stream
    Then the accumulated slot for index 0 has id "call_id_1"
    And the accumulated slot for index 0 has name "read_file"
    And messages[1]["tool_calls"][0]["id"] equals "call_id_1"

  Scenario: Two tool calls at different indices accumulate independently
    Given files "a.txt" containing "aaa" and "b.txt" containing "bbb"
    And a scripted model whose turn 1 sends:
      | chunk 1 | index 0, id "c0", name "read_file", arguments for a.txt |
      | chunk 2 | index 1, id "c1", name "read_file", arguments for b.txt |
      | chunk 3 | finish_reason "tool_calls"                              |
    And turn 2 replies "Read both." with finish_reason "stop"
    When run_agent("read both files") completes
    Then messages[1] carries two tool_calls with ids "c0" and "c1"
    And there are two role:"tool" messages in the history
    And the combined content of both tool messages contains "aaa" and "bbb"

  Scenario: Partial JSON is only parsed after finish_reason, never mid-stream
    Given a scripted model that sends a tool call whose arguments span three fragments
    And none of the first two fragments form valid JSON on their own
    When run_agent processes each chunk in sequence
    Then no json.loads call is attempted during the streaming loop
    And json.loads is called exactly once after the async-for block exits
    And the parsed result is the complete, valid arguments dict
```

## Notes / open questions

- All changes are confined to the `async for chunk in stream_response(...)` block and Phase D in `src/agent.py`. `tools.py` and `provider.py` are untouched.
- `setdefault` guarantees exactly one dict per index regardless of how many fragments arrive — prefer it over a manual `if idx not in tool_acc` check.
- The `arguments` key in the assistant turn's `tool_calls` list stays a JSON string (the raw `arguments_buf`) — Phase D is the only place `json.loads` runs, and that result is used for dispatch only, never stored back.
- The two-index scenario in the BDD gate previews parallel tool execution, which is formalized in a later phase.

---

**Tutorial build step 5 of 32** · ← [Phase 4 — Your First Tool](./phase-04-your-first-tool.md) · [Phase 6 — A Toolbox](./phase-06-a-toolbox.md) →
