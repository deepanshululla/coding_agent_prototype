---
sidebar_position: 4
title: "BDD Integration Testing"
description: How to build a BDD-style integration testing framework that drives run_agent with a scripted LLM and asserts on tool calls, file-system effects, error recovery, and agent behavior — no network required.
---

# BDD Integration Testing

Unit tests in [`tests/test_tools.py`](./testing.md#unit-testing-tools-teststest_toolspy) verify individual tools in isolation. The loop tests in `tests/test_agent.py` verify that `run_agent` accumulates streaming chunks correctly and routes tool calls through `TOOL_REGISTRY`. Both are essential.

BDD integration tests are a third layer. They describe **complete agent behaviors** — "given a project with a bug, when the agent is asked to fix it, then it reads the file before editing it and the edited file contains the fix." A scripted LLM makes these scenarios deterministic and fast (no API key, no network, sub-millisecond per-scenario). The result is a living specification of what the agent does, not just what the loop mechanics do.

This page specifies a full BDD framework built on top of the existing `ScriptedLLM` pattern already present in `tests/test_agent.py`.

:::note
The helper classes (`_chunk`, `_tc`, `ScriptedLLM`) in `tests/test_agent.py` are implemented and working. The BDD layer described here is a planned extension of that foundation.
:::

---

## Why BDD here?

### The testing gap

Unit tests answer "does `edit_file` replace text correctly?" and loop tests answer "does the agent send tool results back to the model?" Neither answers "does the agent actually read a file before editing it?" or "does the agent stop and report an error when `bash` is blocked by the allowlist?"

Those are behavioral questions. They can only be answered by driving `run_agent` end-to-end — with a scripted model that controls what gets called — and asserting on the sequence of events that results.

### Why Gherkin (Given/When/Then)?

The agent loop is a stateful, multi-turn process. Scenarios decompose naturally into three phases:

- **Given** — the filesystem state and the scripted model behavior (what tools the model will call).
- **When** — `run_agent(task)` is called.
- **Then** — assertions about the message history, tool call sequence, and filesystem state.

Gherkin makes these phases explicit in prose that can be read without understanding the test harness. A product owner, a security reviewer, or a future contributor can read a `.feature` file and understand what the agent is supposed to do.

### Why a scripted LLM?

A scripted LLM:

- **Eliminates flakiness.** No network, no rate limits, no model drift between versions.
- **Provides control.** You decide exactly what tool calls the model makes, in what order, so you're testing agent behavior rather than model judgment.
- **Runs in milliseconds.** The entire BDD suite can run on every commit without cost.
- **Is already built.** `ScriptedLLM` in `tests/test_agent.py` provides the exact interface needed; the BDD layer just adds structure and assertions around it.

### Relationship to existing tests

| Layer | File | What it tests |
|---|---|---|
| Unit (tools) | `tests/test_tools.py` | Individual tool functions, error strings, edge cases |
| Loop integration | `tests/test_agent.py` | Streaming accumulation, tool dispatch, message history shape |
| BDD integration | `tests/features/*.feature` | End-to-end agent behaviors, tool sequences, filesystem effects |

The BDD layer does not replace the others. It adds behavior-level coverage on top. See [Testing the Agent](./testing.md) for the lower two layers.

---

## Recommended stack

### Option A: pytest-bdd (Gherkin)

[pytest-bdd](https://pytest-bdd.readthedocs.io/) lets you write `.feature` files in Gherkin and bind each step to a Python function. It integrates with pytest fixtures so `ScriptedLLM`, `tmp_path`, and `monkeypatch` all work without modification.

```bash
uv add --dev pytest-bdd
```

Verify:

```bash
uv run pytest --collect-only tests/features/
```

### Option B: Pure pytest (no Gherkin)

If you prefer to stay in Python without `.feature` files, structure scenarios as regular test functions with a naming convention and explicit phase comments. This is lighter but loses the prose readability of Gherkin.

```python
# tests/bdd/test_safe_edits.py

def test_agent_reads_before_editing(agent_world):
    # Given: a file exists and the scripted LLM calls read_file then edit_file
    # When: run_agent is called
    # Then: read_file appears before edit_file in the tool call log
    ...
```

Both options share the same `AgentWorld` fixture. This page shows pytest-bdd; adapt the step definitions to plain functions for Option B.

---

## Directory layout

```
tests/
├── test_tools.py          # unit tests (existing)
├── test_agent.py          # loop integration tests (existing)
├── conftest.py            # shared fixtures: AgentWorld, ScriptedLLM helpers
├── features/
│   ├── safe_edits.feature
│   ├── error_recovery.feature
│   ├── parallel_tools.feature
│   ├── allowlist.feature
│   └── max_iterations.feature
└── steps/
    ├── __init__.py
    ├── common_steps.py    # Given steps shared across features
    ├── safe_edits_steps.py
    ├── error_recovery_steps.py
    ├── parallel_tools_steps.py
    ├── allowlist_steps.py
    └── max_iterations_steps.py
```

:::tip
Keep step definitions co-located with their feature when a step is only used in one scenario. Move steps to `common_steps.py` when two or more features share them.
:::

---

## The harness: `AgentWorld`

`AgentWorld` is the central test fixture. It provides:

1. A temporary working directory seeded with files you control.
2. A `ScriptedLLM` that returns canned turns (reusing the same `_chunk`/`_tc` helpers).
3. A tool-call recorder that captures every `(name, args)` pair executed.
4. The `messages` list returned by `run_agent`.

### `tests/conftest.py`

```python
# tests/conftest.py
import asyncio
import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

import agent


# ── Chunk / fragment builders (same shape as tests/test_agent.py) ────────────

def _chunk(content=None, tool_calls=None, finish_reason=None):
    """Build one OpenAI-style streaming chunk."""
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


def _tc(index, id=None, name=None, arguments=None):
    """Build one tool-call fragment inside a delta."""
    fn = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=id, function=fn)


class ScriptedLLM:
    """Yields a different scripted turn (list of chunks) on each call.

    Each element of *turns* is a list of chunks that will be yielded on the
    corresponding invocation of stream_response.
    """

    def __init__(self, turns):
        self._turns = list(turns)

    def __call__(self, messages, system_prompt):
        chunks = self._turns.pop(0)

        async def _gen():
            for c in chunks:
                yield c

        return _gen()


# ── Tool-call recorder ───────────────────────────────────────────────────────

@dataclass
class ToolCallRecord:
    name: str
    args: dict[str, Any]


class RecordingRegistry:
    """Wraps TOOL_REGISTRY to record every dispatched tool call."""

    def __init__(self, real_registry: dict, log: list[ToolCallRecord]):
        self._real = real_registry
        self._log = log

    def get(self, name: str):
        real_fn = self._real.get(name)
        if real_fn is None:
            return None

        async def _wrapper(**kwargs):
            self._log.append(ToolCallRecord(name=name, args=dict(kwargs)))
            return await real_fn(**kwargs)

        return _wrapper


# ── AgentWorld fixture ───────────────────────────────────────────────────────

@dataclass
class AgentWorld:
    """Everything a BDD step needs to set up and interrogate an agent run."""
    tmp_dir: Any                              # pathlib.Path (pytest's tmp_path)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    _scripted_llm: ScriptedLLM | None = None

    def seed_file(self, name: str, content: str) -> None:
        """Write *content* to *name* inside the tmp_dir."""
        (self.tmp_dir / name).write_text(content)

    def read_file(self, name: str) -> str:
        """Read *name* from the tmp_dir after the agent has run."""
        return (self.tmp_dir / name).read_text()

    def script_turns(self, turns: list) -> None:
        """Supply the scripted LLM turns that will be consumed during the run."""
        self._scripted_llm = ScriptedLLM(turns)

    def run(self, task: str) -> None:
        """Drive run_agent(task) synchronously and capture results."""
        if self._scripted_llm is None:
            raise RuntimeError("Call world.script_turns() before world.run()")
        self.messages = asyncio.run(agent.run_agent(task))

    # ── Assertion helpers ────────────────────────────────────────────────────

    def tool_names_in_order(self) -> list[str]:
        return [r.name for r in self.tool_calls]

    def calls_of(self, name: str) -> list[ToolCallRecord]:
        return [r for r in self.tool_calls if r.name == name]

    def final_answer(self) -> str:
        for msg in reversed(self.messages):
            if msg["role"] == "assistant" and msg.get("content"):
                return msg["content"]
        return ""

    def tool_messages(self) -> list[dict]:
        return [m for m in self.messages if m["role"] == "tool"]

    def assistant_turns(self) -> list[dict]:
        return [m for m in self.messages if m["role"] == "assistant"]


@pytest.fixture
def agent_world(tmp_path, monkeypatch):
    world = AgentWorld(tmp_dir=tmp_path)
    recording_registry = RecordingRegistry(agent.TOOL_REGISTRY, world.tool_calls)

    def _patched_stream(messages, system_prompt):
        return world._scripted_llm(messages, system_prompt)

    monkeypatch.setattr(agent, "stream_response", _patched_stream)
    monkeypatch.setattr(agent, "TOOL_REGISTRY", recording_registry)

    yield world
```

:::note
`RecordingRegistry` wraps the **real** `TOOL_REGISTRY` so tools actually run against the filesystem. This means `read_file` on a seeded file returns real content, and `write_file` produces a real file that you can assert on. Replace individual tools with stubs only when the real implementation would have side effects you don't want (e.g., `bash` running network commands).
:::

---

## Example feature file

### `tests/features/safe_edits.feature`

```gherkin
Feature: Safe edits
  The agent must read a file before editing it so it understands the current
  content. Blind writes risk corrupting code that the model has not seen.

  Background:
    Given a file "hello.py" containing:
      """
      def greet():
          return "hello"
      """

  Scenario: The agent reads a file before editing it
    Given the scripted model will call read_file then edit_file
    When the agent is asked to "change the greeting to goodbye in hello.py"
    Then the tool call log contains "read_file" before "edit_file"
    And the file "hello.py" contains "goodbye"

  Scenario: A failed edit is reported back to the model
    Given the scripted model will call edit_file with a bad old_string
    When the agent is asked to "edit hello.py"
    Then the tool result for "edit_file" contains "error"
    And the model receives the error and continues

  Scenario: An unknown command is refused
    Given the scripted model will call bash with "rm -rf /"
    When the agent is asked to "delete everything"
    Then the tool result for "bash" contains "not allowed"
    And the final answer mentions the restriction
```

---

## Step definitions

### `tests/steps/safe_edits_steps.py`

```python
# tests/steps/safe_edits_steps.py
import json
import pytest
from pytest_bdd import given, when, then, parsers, scenarios

from conftest import _chunk, _tc

scenarios("../features/safe_edits.feature")


# ── Background ────────────────────────────────────────────────────────────────

@given(parsers.parse('a file "{name}" containing:\n{content}'))
def seed_file(agent_world, name, content):
    # Strip leading/trailing whitespace from the docstring block.
    agent_world.seed_file(name, content.strip() + "\n")


# ── Scenario: reads before editing ───────────────────────────────────────────

@given("the scripted model will call read_file then edit_file")
def script_read_then_edit(agent_world):
    file_path = str(agent_world.tmp_dir / "hello.py")

    # Turn 1: model requests read_file
    turn1 = [
        _chunk(tool_calls=[_tc(0, id="c0", name="read_file",
                               arguments=f'{{"path": "{file_path}"}}}')]),
        _chunk(finish_reason="tool_calls"),
    ]
    # Turn 2: model requests edit_file after seeing the content
    turn2 = [
        _chunk(tool_calls=[_tc(0, id="c1", name="edit_file",
                               arguments=json.dumps({
                                   "path": file_path,
                                   "old_string": 'return "hello"',
                                   "new_string": 'return "goodbye"',
                               }))]),
        _chunk(finish_reason="tool_calls"),
    ]
    # Turn 3: final answer
    turn3 = [
        _chunk(content="Done. The greeting is now goodbye."),
        _chunk(finish_reason="stop"),
    ]
    agent_world.script_turns([turn1, turn2, turn3])


@when(parsers.parse('the agent is asked to "{task}"'))
def run_agent_with_task(agent_world, task):
    agent_world.run(task)


@then(parsers.parse('the tool call log contains "{first}" before "{second}"'))
def assert_order(agent_world, first, second):
    names = agent_world.tool_names_in_order()
    assert first in names, f"Expected {first!r} in tool calls, got {names}"
    assert second in names, f"Expected {second!r} in tool calls, got {names}"
    assert names.index(first) < names.index(second), (
        f"Expected {first!r} before {second!r}, got order: {names}"
    )


@then(parsers.parse('the file "{name}" contains "{text}"'))
def assert_file_contains(agent_world, name, text):
    content = agent_world.read_file(name)
    assert text in content, f"Expected {text!r} in {name!r}, got:\n{content}"


# ── Scenario: failed edit is reported ────────────────────────────────────────

@given("the scripted model will call edit_file with a bad old_string")
def script_bad_edit(agent_world):
    file_path = str(agent_world.tmp_dir / "hello.py")

    turn1 = [
        _chunk(tool_calls=[_tc(0, id="c0", name="edit_file",
                               arguments=json.dumps({
                                   "path": file_path,
                                   "old_string": "THIS_DOES_NOT_EXIST",
                                   "new_string": "something",
                               }))]),
        _chunk(finish_reason="tool_calls"),
    ]
    # Model sees the error and gives a final answer
    turn2 = [
        _chunk(content="The old string was not found; no changes were made."),
        _chunk(finish_reason="stop"),
    ]
    agent_world.script_turns([turn1, turn2])


@then(parsers.parse('the tool result for "{tool_name}" contains "{text}"'))
def assert_tool_result_contains(agent_world, tool_name, text):
    # Find the assistant turn with this tool call, then the subsequent tool message.
    for msg in agent_world.messages:
        if msg["role"] == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                if tc["function"]["name"] == tool_name:
                    call_id = tc["id"]
                    # Find the tool result message for this call_id.
                    for result_msg in agent_world.messages:
                        if (result_msg["role"] == "tool"
                                and result_msg["tool_call_id"] == call_id):
                            assert text.lower() in result_msg["content"].lower(), (
                                f"Expected {text!r} in tool result for {tool_name!r}:\n"
                                f"{result_msg['content']}"
                            )
                            return
    pytest.fail(f"No tool result found for {tool_name!r}")


@then("the model receives the error and continues")
def assert_model_continued(agent_world):
    # The agent must have at least two assistant turns (one with the tool call,
    # one with a text response after receiving the error).
    turns = agent_world.assistant_turns()
    assert len(turns) >= 2, (
        f"Expected at least 2 assistant turns (tool call + recovery), got {len(turns)}"
    )


# ── Scenario: unknown command refused ────────────────────────────────────────

@given(parsers.parse('the scripted model will call bash with "{cmd}"'))
def script_bash_blocked(agent_world, cmd):
    turn1 = [
        _chunk(tool_calls=[_tc(0, id="c0", name="bash",
                               arguments=json.dumps({"cmd": cmd}))]),
        _chunk(finish_reason="tool_calls"),
    ]
    turn2 = [
        _chunk(content="I cannot run that command as it is not permitted."),
        _chunk(finish_reason="stop"),
    ]
    agent_world.script_turns([turn1, turn2])


@then(parsers.parse('the final answer mentions "{keyword}"'))
def assert_final_answer_mentions(agent_world, keyword):
    answer = agent_world.final_answer()
    assert keyword.lower() in answer.lower(), (
        f"Expected {keyword!r} in final answer: {answer!r}"
    )
```

---

## Full taxonomy of behavioral assertions

This section catalogs every class of behavioral assertion with the corresponding snippet. Use this as a reference when writing new scenarios.

### 1. Tool call sequence

Assert that specific tools were called and in a specific order. The `tool_names_in_order()` helper on `AgentWorld` returns the names in dispatch order.

```python
def test_reads_before_writes(agent_world):
    # ... script_turns and run ...
    names = agent_world.tool_names_in_order()
    read_pos = names.index("read_file")
    edit_pos = names.index("edit_file")
    assert read_pos < edit_pos
```

### 2. Parallel tool calls in one turn

When the model emits two tool-call fragments in a single streaming turn (different `index` values), the agent executes them with `asyncio.gather`. Both tool call records appear in the log, and both tool result messages appear in the history before the next assistant turn.

```python
def test_parallel_reads(agent_world, tmp_path):
    (tmp_path / "a.txt").write_text("aaa")
    (tmp_path / "b.txt").write_text("bbb")

    turn1 = [
        _chunk(tool_calls=[
            _tc(0, id="c0", name="read_file",
                arguments=f'{{"path": "{tmp_path / "a.txt"}"}}'),
            _tc(1, id="c1", name="read_file",
                arguments=f'{{"path": "{tmp_path / "b.txt"}"}}'),
        ]),
        _chunk(finish_reason="tool_calls"),
    ]
    turn2 = [_chunk(content="Read both."), _chunk(finish_reason="stop")]
    agent_world.script_turns([turn1, turn2])
    agent_world.run("read a and b")

    # Both tool calls were dispatched
    assert len(agent_world.tool_calls) == 2
    call_names = {r.name for r in agent_world.tool_calls}
    assert call_names == {"read_file"}

    # Both tool result messages appear in history with correct IDs
    tool_msgs = agent_world.tool_messages()
    assert {m["tool_call_id"] for m in tool_msgs} == {"c0", "c1"}

    # Both file contents appear somewhere in the results
    combined = "".join(m["content"] for m in tool_msgs)
    assert "aaa" in combined and "bbb" in combined
```

See [Parallel Tool Execution](../tools/parallel-execution.md) for the implementation detail.

### 3. Arguments passed to tools

Assert on the exact arguments the model sent. `RecordingRegistry` captures `kwargs` as a dict.

```python
def test_write_file_args(agent_world):
    # ... script a write_file turn ...
    writes = agent_world.calls_of("write_file")
    assert len(writes) == 1
    assert writes[0].args["path"].endswith("output.txt")
    assert "Hello" in writes[0].args["content"]
```

### 4. File-system effects

After `agent_world.run(task)`, the tmp directory reflects any writes, edits, or deletes the agent performed. Use `agent_world.read_file(name)` or `pathlib.Path` directly.

```python
def test_write_creates_file(agent_world):
    # ... script a write_file turn ...
    agent_world.run("create output.txt")
    content = agent_world.read_file("output.txt")
    assert "expected text" in content
```

```python
def test_edit_modifies_file(agent_world):
    agent_world.seed_file("config.toml", 'debug = false\n')
    # ... script an edit_file turn ...
    agent_world.run("enable debug in config.toml")
    assert "debug = true" in agent_world.read_file("config.toml")
```

### 5. Final assistant message content

```python
def test_final_answer_summarizes_result(agent_world):
    # ...
    answer = agent_world.final_answer()
    assert "created" in answer.lower()
    assert "output.txt" in answer
```

### 6. Error recovery: tool returns `is_error`

When a tool returns an error string (e.g., `read_file` on a missing path, or `edit_file` when `old_string` is not found), the agent appends the error as a tool result message and calls the model again. The model must then produce a recovery turn.

```python
def test_model_adapts_after_tool_error(agent_world, tmp_path):
    missing = str(tmp_path / "nonexistent.py")

    turn1 = [
        _chunk(tool_calls=[_tc(0, id="c0", name="read_file",
                               arguments=f'{{"path": "{missing}"}}'
                               )]),
        _chunk(finish_reason="tool_calls"),
    ]
    # Model sees the error and pivots
    turn2 = [
        _chunk(content="The file does not exist. I cannot proceed."),
        _chunk(finish_reason="stop"),
    ]
    agent_world.script_turns([turn1, turn2])
    agent_world.run("read nonexistent.py")

    tool_msgs = agent_world.tool_messages()
    assert len(tool_msgs) == 1
    # The tool result carries an error string
    assert "error" in tool_msgs[0]["content"].lower() or "no such" in tool_msgs[0]["content"].lower()

    # The model got a second turn and produced a final answer
    turns = agent_world.assistant_turns()
    assert len(turns) == 2
    assert "not exist" in agent_world.final_answer().lower()
```

See [Tool Error Handling](../tools/error-handling.md) for how `is_error` flows through the message history.

### 7. Stopping at MAX_ITERATIONS

If the model never stops calling tools, the agent breaks after `MAX_ITERATIONS = 30` inner-loop iterations. Test this by scripting a model that always returns a tool call and patching the constant to a low value.

```python
def test_stops_at_max_iterations(agent_world, monkeypatch):
    import agent as agent_module
    monkeypatch.setattr(agent_module, "MAX_ITERATIONS", 3)

    # Supply more turns than the limit; the loop must stop consuming them.
    infinite_turns = []
    for i in range(10):
        infinite_turns.append([
            _chunk(tool_calls=[_tc(0, id=f"c{i}", name="list_dir",
                                   arguments=f'{{"path": "{agent_world.tmp_dir}"}}'
                                   )]),
            _chunk(finish_reason="tool_calls"),
        ])

    agent_world.script_turns(infinite_turns)
    agent_world.run("keep listing forever")

    # The agent stopped; tool calls are capped at MAX_ITERATIONS
    assert len(agent_world.tool_calls) <= 3
```

:::warning
Always patch `MAX_ITERATIONS` to a small value in runaway tests. Without it, the test will consume all scripted turns and then raise `IndexError` when `ScriptedLLM` exhausts its list — a less clear failure.
:::

### 8. Unknown tool is reported, not raised

The agent looks up the tool name in `TOOL_REGISTRY`. If the name is missing, it returns an error string as the tool result and continues. The loop does not crash.

```python
def test_unknown_tool_does_not_crash(agent_world):
    turn1 = [
        _chunk(tool_calls=[_tc(0, id="c0", name="no_such_tool", arguments="{}")]),
        _chunk(finish_reason="tool_calls"),
    ]
    turn2 = [_chunk(content="ok"), _chunk(finish_reason="stop")]
    agent_world.script_turns([turn1, turn2])
    agent_world.run("call a nonexistent tool")

    tool_result = agent_world.tool_messages()[0]
    assert "Unknown tool" in tool_result["content"]
    # The agent still finished with a final answer
    assert agent_world.final_answer() == "ok"
```

### 9. Allowlist denials

The `bash` tool enforces a command allowlist. Commands not on the list return an error string; the agent never executes the shell command. Assert that the tool result contains the denial reason and that the command was not actually executed.

```python
def test_blocked_command_is_denied(agent_world):
    turn1 = [
        _chunk(tool_calls=[_tc(0, id="c0", name="bash",
                               arguments='{"cmd": "curl http://example.com"}')]),
        _chunk(finish_reason="tool_calls"),
    ]
    turn2 = [
        _chunk(content="curl is not permitted; I cannot fetch external URLs."),
        _chunk(finish_reason="stop"),
    ]
    agent_world.script_turns([turn1, turn2])
    agent_world.run("fetch http://example.com")

    tool_result = agent_world.tool_messages()[0]
    # The denial should be explicit
    assert "not allowed" in tool_result["content"].lower() or "denied" in tool_result["content"].lower()
    # Final answer acknowledges the restriction
    assert "not permitted" in agent_world.final_answer().lower() or "cannot" in agent_world.final_answer().lower()
```

See [Command Allowlist](../operations/command-allowlist.md) for the list of permitted commands and how to extend it.

---

## Additional feature examples

### `tests/features/parallel_tools.feature`

```gherkin
Feature: Parallel tool execution
  When the model requests multiple tools in a single turn, the agent executes
  them concurrently and returns all results before the next model call.

  Scenario: Two reads execute in parallel
    Given files "a.txt" and "b.txt" exist
    And the scripted model will call read_file on both in one turn
    When the agent is asked to "summarize both files"
    Then both "read_file" calls appear in the tool log
    And the tool results for both calls appear before the next assistant turn
    And the final answer references both files
```

### `tests/features/max_iterations.feature`

```gherkin
Feature: MAX_ITERATIONS guard
  The agent stops after 30 inner-loop iterations regardless of what the model
  requests, preventing runaway tasks from consuming unbounded resources.

  Scenario: Agent stops when model never halts
    Given the scripted model always returns a tool call
    And MAX_ITERATIONS is patched to 3
    When the agent is asked to "run forever"
    Then the agent completes without hanging
    And at most 3 tool calls were dispatched
```

### `tests/features/error_recovery.feature`

```gherkin
Feature: Error recovery
  Tool errors are fed back to the model as tool result messages. The model
  can then diagnose and recover rather than the agent crashing.

  Scenario: Missing file triggers model recovery
    Given no file "data.csv" exists
    And the scripted model will first call read_file then explain the error
    When the agent is asked to "process data.csv"
    Then the tool result for "read_file" contains "error"
    And the model receives the error and continues
    And the final answer explains the file is missing
```

---

## Running the BDD suite

```bash
# All BDD scenarios
uv run pytest tests/features/ -v

# One feature file
uv run pytest tests/features/safe_edits.feature -v

# With plain pytest BDD output (no verbose)
uv run pytest tests/features/

# Run the full suite (unit + loop + BDD)
uv run pytest -v

# Stop on first failure
uv run pytest tests/features/ -x
```

Run only the BDD feature suite:

```bash
uv run pytest tests/features/
```

:::tip
Pass `-k "reads before"` to run a single scenario by substring matching its title. pytest-bdd maps Gherkin scenario names to test IDs so `pytest -k "reads before editing"` selects exactly that scenario.
:::

---

## Writing new scenarios: checklist

When adding a new scenario, work through this checklist:

1. **Write the `.feature` file first.** The Gherkin is the spec; make it readable without looking at step definitions.
2. **Run `pytest --collect-only tests/features/`** to confirm pytest-bdd finds the new scenario. It will fail with "step not found" if any step is unimplemented — that's the right starting point.
3. **Implement the missing steps** in the appropriate `tests/steps/` file. Use `@given`, `@when`, `@then` from `pytest_bdd`.
4. **Script the LLM turns.** Think carefully about what the model would actually do in this scenario and encode that in `ScriptedLLM`. The scripted turns are the behavioral contract.
5. **Run the test and confirm it fails** for the right reason (assertion, not import error or `IndexError` from exhausted turns).
6. **Implement or adjust code** until the test passes.
7. **Assert on the right things.** A scenario that only asserts `final_answer() != ""` is not useful. Assert on tool order, file contents, or specific message content.

---

## Pitfalls

### `ScriptedLLM` runs out of turns

If `run_agent` calls `stream_response` more times than you scripted, `_turns.pop(0)` raises `IndexError`. This means your scenario underestimated how many turns the loop takes. Add a final `finish_reason="stop"` turn to handle the extra call.

### Monkeypatching order matters

`agent.TOOL_REGISTRY` is imported at module level. Monkeypatch `agent.TOOL_REGISTRY` (on the module object) rather than `tools.TOOL_REGISTRY` (on the source module), otherwise the agent loop continues using the real registry.

```python
# Correct: patch the name on the agent module
monkeypatch.setattr(agent, "TOOL_REGISTRY", recording_registry)

# Wrong: agent.py already imported TOOL_REGISTRY by the time this runs
monkeypatch.setattr(tools, "TOOL_REGISTRY", recording_registry)
```

`AgentWorld`'s fixture already does this correctly.

### Gherkin docstrings strip inconsistently

When passing a docstring block (`""" ... """`) in Gherkin, pytest-bdd passes it as the `content` parameter with leading/trailing newlines. Always `.strip()` in the step definition before writing to the filesystem:

```python
@given(parsers.parse('a file "{name}" containing:\n{content}'))
def seed_file(agent_world, name, content):
    agent_world.seed_file(name, content.strip() + "\n")
```

### Async and `asyncio.run`

`run_agent` is `async`. `AgentWorld.run()` wraps it with `asyncio.run()`, which is safe for synchronous test functions. Do not call `asyncio.run()` in step definitions directly — delegate to `agent_world.run()`.

---

## Related pages

- [Testing the Agent](./testing.md) — unit tests for tools and loop integration tests; the foundation this BDD layer builds on
- [Architecture: The Agent Loop](../architecture/the-agent-loop.md) — phases A–E of the inner loop; understanding these helps you script realistic LLM turns
- [Tool Error Handling](../tools/error-handling.md) — how `is_error` strings flow through the message history
- [Parallel Tool Execution](../tools/parallel-execution.md) — how `asyncio.gather` runs tool calls concurrently
- [Command Allowlist](../operations/command-allowlist.md) — the `bash` tool allowlist and how to extend it
- [Contributing: Development Workflow](../contributing/development-workflow.md) — TDD loop, plan-first approach, and commit conventions
