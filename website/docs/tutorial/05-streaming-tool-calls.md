---
sidebar_position: 6
title: Phase 5 — Streaming Tool Calls
description: Tool-call arguments arrive as partial JSON across chunks — buffer fragments by index and json.loads only after the stream ends.
---

# Phase 5 — Streaming Tool Calls

:::note Starting point
Phase 4's loop with one `read_file` tool, assuming each tool call arrives whole. This phase handles the realistic case: arguments split across stream chunks.
:::

Phase 4 treated each tool call's arguments as arriving in one chunk. That works in non-streaming mode but breaks with `stream=True`: a model can spread `arguments` across many small fragments, just like it spreads text content. This phase fixes that by accumulating argument fragments into a buffer keyed by `index`, then parsing the complete JSON only once the stream ends.

This is the trickiest part of the streaming protocol. The real `src/agent.py` handles it exactly this way.

## What you'll learn

Why tool-call arguments arrive as partial JSON strings, why you must buffer by `index` rather than appending naively, and why `id` and `name` appear only on the *first* fragment for each tool call. You learn the `tool_acc` accumulation pattern and when it is safe to call `json.loads`.

## Build it

The fix is entirely inside the `async for chunk in stream_response(...)` block in `src/agent.py`. Nothing changes in `tools.py` or `provider.py`.

### The accumulation pattern

Replace the simplified fragment handling from Phase 4 with this:

```python
# src/agent.py  — Phase A (streaming accumulation), complete version

text_buf = ""
tool_acc: dict[int, dict] = {}   # index → {id, name, arguments_buf}
finish_reason = None

async for chunk in stream_response(messages, system_prompt):
    choice = chunk.choices[0]
    delta = choice.delta
    finish_reason = choice.finish_reason or finish_reason

    # Text fragment
    if getattr(delta, "content", None):
        text_buf += delta.content
        print(delta.content, end="", flush=True)

    # Tool call fragments — may arrive across many chunks
    for tc_chunk in getattr(delta, "tool_calls", None) or []:
        idx = tc_chunk.index
        slot = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments_buf": ""})

        # id and name only appear on the first chunk for this index
        if tc_chunk.id:
            slot["id"] = tc_chunk.id
        fn = getattr(tc_chunk, "function", None)
        if fn and fn.name:
            slot["name"] = fn.name
            print(f"\n▸ {fn.name}", end="", flush=True)
        if fn and fn.arguments:
            slot["arguments_buf"] += fn.arguments   # concatenate partial JSON

print()  # newline after the turn

# Finalize — parse arguments ONCE, after the stream ends
tool_calls = [
    {
        "id": tc["id"],
        "type": "function",
        "function": {
            "name": tc["name"],
            "arguments": tc["arguments_buf"],   # keep as string in history
        },
    }
    for tc in tool_acc.values()
]
```

Then, in Phase D where you dispatch:

```python
# Phase D — parse here, not mid-stream
parsed_calls = [
    {
        "id": tc["id"],
        "name": tc["function"]["name"],
        "input": json.loads(tc["function"]["arguments"] or "{}"),
    }
    for tc in tool_calls
]
```

### Why each design decision

| Decision | Reason |
|----------|--------|
| Buffer by `index`, not sequentially | The model can interleave fragments from multiple tool calls in the same turn; `index` is the stable key per call |
| `setdefault` to create the slot | Guarantees exactly one dict per index regardless of how many fragments arrive for it |
| `if tc_chunk.id:` guard before assigning | Later fragments for the same index have `id=None`; overwriting with `None` would corrupt the history |
| `arguments_buf += fn.arguments` | `fn.arguments` is a JSON fragment (e.g. `'{"pa'` then `'th": "foo.py"}'`); concatenation rebuilds the valid string |
| `json.loads` only after the stream | Parsing a partial string mid-stream always raises `JSONDecodeError` |
| `arguments` stays a string in history | Providers round-trip the string form verbatim; converting to a dict corrupts the re-serialization |

### Why `id` and `name` appear only on the first chunk

The streaming protocol sends metadata (call id, function name) exactly once — on the first fragment for each `index`. Every subsequent fragment for that call carries only the next piece of `arguments`. If you re-assign `slot["id"]` or `slot["name"]` on every chunk you would overwrite them with `None` or `""`. The `if tc_chunk.id:` and `if fn and fn.name:` guards prevent that.

## Test it

Write the failing test first. The test splits a `read_file` call's arguments across two chunks, exactly as a real streaming response would.

```python
# tests/test_agent.py  — add this test

def test_streaming_tool_call_split_arguments(monkeypatch, tmp_path):
    """Arguments fragmented across chunks are joined before json.loads."""
    target = tmp_path / "data.txt"
    target.write_text("streaming works")

    path_str = str(target)
    # Split the JSON arguments string across two chunks.
    half = len(path_str) // 2
    args_part1 = f'{{"path": "{path_str[:half]}'
    args_part2 = f'{path_str[half:]}"}}'

    turn1 = [
        # First fragment: carries id, name, and the first half of arguments.
        _chunk(
            tool_calls=[
                _tc(0, id="call_split", name="read_file", arguments=args_part1)
            ]
        ),
        # Second fragment: no id, no name, just the rest of arguments.
        _chunk(
            tool_calls=[_tc(0, arguments=args_part2)]
        ),
        _chunk(finish_reason="tool_calls"),
    ]
    turn2 = [
        _chunk(content="File content received."),
        _chunk(finish_reason="stop"),
    ]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM([turn1, turn2]))

    messages = asyncio.run(agent.run_agent("read the data file"))

    # The tool_calls entry in the assistant message has the full joined arguments.
    assistant1 = messages[1]
    args_str = assistant1["tool_calls"][0]["function"]["arguments"]
    assert isinstance(args_str, str)
    parsed = json.loads(args_str)
    assert parsed["path"] == path_str

    # The tool ran and produced a role:tool message with the file content.
    tool_msg = messages[2]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "call_split"
    assert "streaming works" in tool_msg["content"]
```

You also need `import json` at the top of the test file. Run the test:

```bash
uv run pytest tests/test_agent.py::test_streaming_tool_call_split_arguments -v
```

Confirm it fails before the fix (the test will raise `JSONDecodeError` or an assertion error on the arguments string), then make it pass. Expected output:

```
tests/test_agent.py::test_streaming_tool_call_split_arguments PASSED
```

Run the full suite to make sure nothing regressed:

```bash
uv run pytest tests/test_agent.py -v
```

### Behavior (BDD)

Verify this phase as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

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

Run this as an integration scenario with the [BDD framework](../guides/bdd-integration-testing.md) — `pytest-bdd` over the `ScriptedLLM` harness from Phase 9. The unit test above proves the mechanism; this scenario specifies the *behavior*.

## Run it

This is the same task as Phase 4, but now the streaming path handles argument fragmentation correctly:

```bash
uv run main.py "read src/agent.py and summarize what the inner loop does"
```

You should see the tool name print as soon as the first fragment arrives, the executing log line, and then the model's summary:

```
▸ read_file
  [executing read_file {'path': 'src/agent.py'}]
  [✓ read_file: 3821 chars]

The inner loop streams a response from the model, accumulates text and tool-call
fragments, appends the assistant turn to history, executes any tool calls in parallel,
and pushes tool results back before looping again.
```

The difference from Phase 4 is invisible in happy-path output — but without this phase, arguments fragmented across chunks would fail with a JSON parse error.

:::tip Verify the fix yourself
Add a quick `print(repr(fn.arguments))` inside the `if fn and fn.arguments:` block, run the task, and watch the fragments arrive. You'll see strings like `'{"path"'`, `': "src/ag'`, `'ent.py"}'` — each one a valid string, but not valid JSON on its own.
:::

## Recap

Tool-call arguments arrive as partial JSON strings spread across chunks, identified by `index`. The accumulation loop uses `tool_acc: dict[int, dict]` to buffer each call's fragments by index, applies `id` and `name` only from the first fragment (subsequent ones have `None`), and concatenates `arguments_buf` until the stream ends. Only then does `json.loads` run — on the complete string. The result is stored as the JSON string in message history so providers can round-trip it unchanged.

For the full event shape and a deeper look at the streaming protocol, see [Streaming and Events](../architecture/streaming-and-events.md). For debugging when fragments arrive in unexpected forms, see [Debugging Streaming](../guides/debugging-streaming.md).
