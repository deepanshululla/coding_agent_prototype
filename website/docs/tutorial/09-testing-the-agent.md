---
sidebar_position: 10
title: "Phase 9 — Testing the Agent"
description: Make the agent loop deterministically testable without any network call by replacing stream_response with a scripted fake that yields canned OpenAI-format chunks.
---

# Phase 9 — Testing the Agent

:::note Starting point
Phase 8's finished agent (`run_agent` + `main.py`). This phase locks its behavior in with deterministic tests.
:::

You have a working agent. Before going further, lock in what it does. The agent loop talks to a real LLM over the network — that's not testable. This phase shows you how to replace the network call with a scripted fake that yields exactly the chunks you script, so every behavior you care about can be asserted without an API key, without flakiness, and in milliseconds.

This is why every earlier phase had a "Test it" step: each piece was designed to be independently verifiable, and this phase assembles those pieces into a coherent test suite for the full loop.

## What you'll learn

- How to build a `ScriptedLLM` harness that replaces `stream_response` turn-by-turn.
- How to construct OpenAI-format streaming chunks in Python without any mock library.
- How to monkeypatch `agent.stream_response` so the agent loop never touches the network.
- What the three core behavioral tests assert and why each one matters.
- How to run the full suite and read the output.

## Build it

### The chunk builders: `_chunk` and `_tc`

The agent loop processes objects with the shape `chunk.choices[0].delta.{content, tool_calls}` and `chunk.choices[0].finish_reason`. The real objects come from LiteLLM; for tests you just need something with those attributes.

`types.SimpleNamespace` gives you an object with arbitrary dot-access and no base-class overhead:

```python
# tests/test_agent.py
from types import SimpleNamespace


def _chunk(content=None, tool_calls=None, finish_reason=None):
    """Build one OpenAI-style streaming chunk."""
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


def _tc(index, id=None, name=None, arguments=None):
    """Build one tool-call fragment inside a delta."""
    fn = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=id, function=fn)
```

`_chunk` builds a complete chunk object. `_tc` builds the fragment that sits inside `delta.tool_calls[i]`. A tool-call turn in the real protocol spreads the tool name, ID, and JSON arguments across multiple chunks — you simulate that by calling `_tc` with partial data and passing the resulting list as `tool_calls` to `_chunk`.

### The `ScriptedLLM` class

`stream_response` is an async generator function: called with `(messages, system_prompt)`, it returns an async iterable of chunks. `ScriptedLLM` produces the same interface but drains a pre-built list of "turns" instead of talking to a model:

```python
class ScriptedLLM:
    """Yields a different scripted turn (list of chunks) on each call."""

    def __init__(self, turns):
        self._turns = list(turns)

    def __call__(self, messages, system_prompt):
        chunks = self._turns.pop(0)

        async def _gen():
            for c in chunks:
                yield c

        return _gen()
```

Each element of `turns` is a list of chunks. On the first `stream_response(messages, system_prompt)` call the loop gets the first list; on the second call it gets the second list; and so on. `pop(0)` consumes turns in order, so if the loop makes more calls than you scripted, it raises `IndexError` — a clear signal that your script underestimated the number of turns.

### Monkeypatching `agent.stream_response`

`agent.py` imports `stream_response` from `provider.py` at module level:

```python
from provider import stream_response
```

That means `agent.stream_response` is the name the loop actually calls. Monkeypatching the name on the `agent` module object replaces it for the duration of the test:

```python
monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))
```

Do **not** patch `provider.stream_response`. By the time your test runs, `agent.py` has already bound its own local reference. Patching the source module has no effect.

## Test it

With the harness in place, you can write behavioral tests. These three cover the most important slices of the loop.

### Test 1: plain text turn stops the loop

The simplest possible agent interaction: the model returns a text message and `finish_reason="stop"`. No tools are called. The loop should terminate after one turn and the message history should contain exactly a user message and one assistant message.

```python
def test_plain_text_turn_stops(monkeypatch):
    turns = [
        [
            _chunk(content="Hello, "),
            _chunk(content="world."),
            _chunk(finish_reason="stop"),
        ]
    ]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))

    messages = asyncio.run(agent.run_agent("say hi"))

    assert messages[0] == {"role": "user", "content": "say hi"}
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "Hello, world."
    assert "tool_calls" not in messages[1]
    # No tool was called.
    assert all(m["role"] != "tool" for m in messages)
```

What this asserts about **behavior**:

- The loop consumed all text fragments and concatenated them into `content`. Streaming accumulation works.
- A `finish_reason="stop"` with no tool calls terminates the loop. The stop condition in Phase C of the inner loop fired correctly.
- No spurious `tool_calls` key leaked onto the assistant message. The message shape is clean.

### Test 2: tool call then stop (with fragment buffering)

The real protocol splits tool-call arguments across chunks. Here turn 1 delivers the `arguments` JSON in two fragments: `'{"path": '` and then `'"<path>"}`. The loop must buffer them and `json.loads` the result only after the stream ends.

Turn 2 is a plain text response, simulating the model summarizing the tool result.

```python
def test_tool_call_then_stop(monkeypatch, tmp_path):
    (tmp_path / "marker.txt").write_text("x")

    # Turn 1: the model requests list_dir, arguments split across two fragments.
    turn1 = [
        _chunk(
            tool_calls=[_tc(0, id="call_1", name="list_dir", arguments='{"path": ')],
        ),
        _chunk(
            tool_calls=[_tc(0, arguments=f'"{tmp_path}"' + "}")],
        ),
        _chunk(finish_reason="tool_calls"),
    ]
    # Turn 2: the model summarizes and stops.
    turn2 = [
        _chunk(content="Found marker.txt."),
        _chunk(finish_reason="stop"),
    ]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM([turn1, turn2]))

    messages = asyncio.run(agent.run_agent("list the dir"))

    # Assistant turn 1 carries the tool call; arguments stay a JSON string.
    assistant1 = messages[1]
    assert assistant1["role"] == "assistant"
    assert assistant1["tool_calls"][0]["function"]["name"] == "list_dir"
    assert isinstance(assistant1["tool_calls"][0]["function"]["arguments"], str)

    # A tool result message follows, addressed to the right call id.
    tool_msg = messages[2]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "call_1"
    assert "marker.txt" in tool_msg["content"]

    # Final assistant turn is the summary.
    assert messages[-1]["content"] == "Found marker.txt."
```

What this asserts about **behavior**:

- Fragment buffering works: two partial `arguments` strings are concatenated correctly before parsing.
- The assistant message in history keeps `arguments` as a JSON string, not a parsed dict. The OpenAI message format requires this; the agent must not silently convert it.
- The tool result message is keyed to the correct `tool_call_id`. If the IDs were mismatched the model would receive results it could not match to its requests.
- The tool actually ran against the real filesystem (`marker.txt` appears in the result), not a stub.
- A second `stream_response` call happened (turn 2), confirming the loop re-entered the model after executing the tool.

### Test 3: multiple parallel tool calls

When the model emits two tool-call fragments with different `index` values in the same turn, the loop must execute both with `asyncio.gather` and produce two `role: "tool"` messages before calling the model again.

```python
def test_multiple_parallel_tool_calls(monkeypatch, tmp_path):
    (tmp_path / "a.txt").write_text("aaa")
    (tmp_path / "b.txt").write_text("bbb")

    turn1 = [
        _chunk(
            tool_calls=[
                _tc(0, id="c0", name="read_file", arguments=f'{{"path": "{tmp_path / "a.txt"}"}}'),
                _tc(1, id="c1", name="read_file", arguments=f'{{"path": "{tmp_path / "b.txt"}"}}'),
            ]
        ),
        _chunk(finish_reason="tool_calls"),
    ]
    turn2 = [_chunk(content="done"), _chunk(finish_reason="stop")]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM([turn1, turn2]))

    messages = asyncio.run(agent.run_agent("read both"))

    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert {m["tool_call_id"] for m in tool_msgs} == {"c0", "c1"}
    contents = "".join(m["content"] for m in tool_msgs)
    assert "aaa" in contents and "bbb" in contents
```

What this asserts about **behavior**:

- Both tool calls were dispatched. A sequential implementation would also pass the first assertion, but combining it with a content check on both files confirms both ran.
- Each result carries the correct `tool_call_id`. The model needs both IDs to match results to requests; a bug in the parallel dispatch that crossed IDs would be caught here.
- The real files were read — no stubs — so the `asyncio.gather` path in `_execute_tools_parallel` ran against live I/O.

:::tip
These three tests are the minimum viable behavioral coverage for the loop. They exercise the stop condition, the fragment accumulation path, and the parallel execution path. The fourth test in the shipped suite (`test_unknown_tool_is_reported_not_raised`) covers the error-return contract: an unknown tool name produces a `role: "tool"` message containing `"Unknown tool"` rather than raising an exception.
:::

### Behavior (BDD)

Verify this phase as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Feature: Deterministic offline testing with ScriptedLLM
  The ScriptedLLM harness replaces stream_response so every behavior can be
  asserted without a network call, an API key, or model flakiness.

  Scenario: the full suite runs with no network via ScriptedLLM
    Given agent.stream_response is monkeypatched with a ScriptedLLM instance
    And no ANTHROPIC_API_KEY is set in the environment
    When uv run pytest tests/test_agent.py tests/test_tools.py -q runs
    Then all tests pass (17 or more) without any network connection
    And the run completes in under 5 seconds

  Scenario: a scripted plain-text turn asserts the stop condition
    Given a ScriptedLLM scripted with one turn: [_chunk(content="Hello, "), _chunk(content="world."), _chunk(finish_reason="stop")]
    When run_agent("say hi") is called with that ScriptedLLM patched in
    Then messages[1]["role"] equals "assistant"
    And messages[1]["content"] equals "Hello, world."
    And no message in the history has role "tool"
    And the loop made exactly 1 call to stream_response

  Scenario: a scripted tool turn asserts the role-tool result threading
    Given a ScriptedLLM scripted with turn 1 emitting a list_dir call with id "call_1" and turn 2 returning "Found marker.txt."
    And a temp directory containing "marker.txt"
    When run_agent("list the dir") is called with that ScriptedLLM patched in
    Then messages[2]["role"] equals "tool"
    And messages[2]["tool_call_id"] equals "call_1"
    And messages[2]["content"] contains "marker.txt"
    And messages[-1]["content"] equals "Found marker.txt."

  Scenario: every other phase gate runs on this same ScriptedLLM harness
    Given the ScriptedLLM, _chunk, and _tc helpers defined in tests/test_agent.py
    When any BDD scenario from Phase 6, 7, 8, or 11 is executed
    Then it monkeypatches agent.stream_response (not provider.stream_response)
    And it uses the same _chunk/_tc builders to construct streaming turns
    And it asserts on run_agent's returned messages list without touching the network
```

Run this as an integration scenario with the [BDD framework](../guides/bdd-integration-testing.md) — `pytest-bdd` over the `ScriptedLLM` harness from Phase 9. The unit test above proves the mechanism; this scenario specifies the *behavior*.

:::note
Phase 9 IS the BDD foundation. The `ScriptedLLM`, `_chunk`, and `_tc` helpers defined here are the same harness that every other phase's BDD scenario runs on. When you add `pytest-bdd` and `tests/features/`, those feature files import from the same `conftest.py` that wraps this harness in an `AgentWorld` fixture.
:::

## Run it

```bash
uv run pytest -q
```

You should see:

```
17 passed in <N>s
```

That's 13 tool tests and 4 agent loop tests. Every behavior locked in by every earlier phase is verified in under a second, with no network, no API key, and no flakiness.

To run the two test files separately:

```bash
# Tools only
uv run pytest tests/test_tools.py -v

# Agent loop only
uv run pytest tests/test_agent.py -v
```

:::note
The `pyproject.toml` must have `pythonpath = ["src"]` under `[tool.pytest.ini_options]`. Without it, `import agent` in `test_agent.py` fails with `ModuleNotFoundError`. The repo includes this already; if you cloned a fresh copy and tests don't import, check `pyproject.toml` first.
:::

## Recap

The `ScriptedLLM` / `_chunk` / `_tc` pattern is the testing foundation for this entire codebase. It works because the agent loop only ever touches `stream_response` — it does not import from `litellm` directly. One monkeypatch at the module boundary replaces the entire network layer.

The three tests above verify:

1. **Stop condition** — text-only turns terminate the loop cleanly.
2. **Fragment buffering + tool dispatch + message shape** — the hardest part of the streaming accumulation path.
3. **Parallel execution** — `asyncio.gather` produces one result per call, keyed correctly.

This is also why the tutorial front-loaded the "Test it" step in every phase. Testability isn't an afterthought — it's a design constraint. The clear boundary at `stream_response` exists specifically to make this kind of injection easy.

For deeper coverage, see:
- [Testing the Agent](../guides/testing.md) — the full testing guide with tool unit tests and more loop patterns.
- [BDD Integration Testing](../guides/bdd-integration-testing.md) — a framework that builds on `ScriptedLLM` to write complete behavioral scenarios in Gherkin: "given a project with a bug, when the agent is asked to fix it, then it reads the file before editing it."
