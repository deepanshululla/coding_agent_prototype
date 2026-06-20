---
sidebar_position: 5
title: Strategy Pattern
description: Select a different system prompt, tool subset, and success check for each task type — bug fix, refactor, test generation, dependency upgrade, or provider compatibility work.
---

# Strategy Pattern

A single agent loop with a single system prompt handles a lot. But a bug-fix session needs different context, different tool access, and different criteria for "done" than a dependency upgrade or a refactor. The Strategy pattern packages those differences into interchangeable objects so the loop stays stable while the behavior adapts.

:::note Design guidance, not v1
The shipped core runs a straight-through loop with one fixed `build_system_prompt()` call and the full `TOOL_REGISTRY` available for every task. The Strategy pattern describes the seam where specialization slots in as your use-cases diverge.
:::

## The problem

`run_agent` calls `build_system_prompt()` and exposes every tool in `TOOL_REGISTRY` for every task. That works for a tutorial. It breaks down when:

- A refactor task keeps reaching for `bash` to run tests when it should be re-reading the call sites first.
- A dependency-upgrade task needs to know which version constraints matter — context that clutters the prompt for a simple Q&A.
- A provider-compatibility task (`ProviderCompatibilityStrategy`) needs to check adapter tests, golden responses, model configs, and retry/fallback behavior — none of which are relevant to a one-shot bug fix.
- You want a measurable "done" signal that differs by task type: tests pass for a bug fix, but no API-breaking changes for a refactor.

Hardcoding all of this into `run_agent` with a growing `if task_type == "…":` tree makes the loop fragile and hard to test in isolation.

## The pattern

Define a `Strategy` protocol. Each concrete strategy provides three things:

1. **Extra prompt text** — appended to `build_system_prompt(extra=...)` to sharpen focus.
2. **Tool subset** — a filtered view of `TOOL_REGISTRY` that only exposes what makes sense.
3. **Success check** — a callable that inspects the final message history and returns `True` if the task completed correctly.

```
  task
    │
    ▼
┌─────────────────────────────┐
│  Strategy.select(task)      │  ← picks BugFix / Refactor / TestGen / …
└────────────┬────────────────┘
             │  provides
     ┌───────┼──────────────────────┐
     ▼       ▼                      ▼
  extra   tool_subset          success_check
  prompt  (filtered registry)  (fn: messages→bool)
     │       │                      │
     └───────┴──────────────────────┘
                     │
                     ▼
             run_agent(task, …)
```

## In this project

The seam is in `src/agent.py`. Today, `run_agent` is called like this:

```python
# src/agent.py — current v1
system_prompt = build_system_prompt()   # no extra
messages = [{"role": "user", "content": task}]
# ... full TOOL_REGISTRY is passed to stream_response
```

With strategies, the call site becomes:

```python
# src/agent.py — with Strategy
strategy = Strategy.select(task)
system_prompt = build_system_prompt(extra=strategy.extra_prompt())
tool_registry = strategy.tool_subset(TOOL_REGISTRY)
messages = [{"role": "user", "content": task}]
# ... tool_registry passed instead of TOOL_REGISTRY
```

### The protocol

```python
# src/strategies.py (planned)
from __future__ import annotations
from typing import Protocol, Callable

class Strategy(Protocol):
    def extra_prompt(self) -> str:
        """Additional text appended to the system prompt."""
        ...

    def tool_subset(self, registry: dict) -> dict:
        """Return only the tools this strategy should see."""
        ...

    def success_check(self) -> Callable[[list[dict]], bool]:
        """Return a function that inspects the final message history."""
        ...

    @staticmethod
    def select(task: str) -> "Strategy":
        """Classify the task string and return the matching strategy."""
        task_lower = task.lower()
        if any(k in task_lower for k in ("fix", "bug", "error", "traceback")):
            return BugFixStrategy()
        if any(k in task_lower for k in ("refactor", "rename", "restructure")):
            return RefactorStrategy()
        if any(k in task_lower for k in ("test", "coverage", "spec")):
            return TestGenerationStrategy()
        if any(k in task_lower for k in ("upgrade", "dependency", "bump", "version")):
            return DependencyUpgradeStrategy()
        if any(k in task_lower for k in ("litellm", "provider", "adapter", "compat")):
            return ProviderCompatibilityStrategy()
        return DefaultStrategy()
```

### Concrete strategies

```python
# src/strategies.py (planned, continued)

READ_ONLY = {"read_file", "grep", "find_files", "list_dir", "bash"}
ALL_TOOLS = None  # sentinel: pass full registry unchanged

class BugFixStrategy:
    def extra_prompt(self) -> str:
        return (
            "## Bug-fix mode\n"
            "Reproduce the failure first (run the test or command that triggers it).\n"
            "Identify the root cause before editing any file.\n"
            "After the fix, re-run the failing test and confirm it passes."
        )

    def tool_subset(self, registry: dict) -> dict:
        return registry  # all tools available

    def success_check(self):
        def check(messages: list[dict]) -> bool:
            # look for a bash result with exit code 0 from a test run
            for m in messages:
                if m.get("role") == "tool" and "passed" in (m.get("content") or ""):
                    return True
            return False
        return check


class RefactorStrategy:
    def extra_prompt(self) -> str:
        return (
            "## Refactor mode\n"
            "Do not change observable behavior. Read all call sites before editing.\n"
            "Prefer edit_file over write_file. Run tests after each logical change unit.\n"
            "Flag any API-breaking changes explicitly in your text response."
        )

    def tool_subset(self, registry: dict) -> dict:
        return registry

    def success_check(self):
        def check(messages: list[dict]) -> bool:
            # no API-breaking change warning found and tests pass
            last_text = next(
                (m["content"] for m in reversed(messages)
                 if m.get("role") == "assistant" and m.get("content")),
                ""
            )
            return "api-breaking" not in last_text.lower()
        return check


class TestGenerationStrategy:
    def extra_prompt(self) -> str:
        return (
            "## Test-generation mode\n"
            "Read the module under test before writing any test.\n"
            "Mirror the project's existing test style (fixtures, naming, `pytest` or `unittest`).\n"
            "Run the new tests with bash to confirm they pass before finishing."
        )

    def tool_subset(self, registry: dict) -> dict:
        return registry

    def success_check(self):
        def check(messages: list[dict]) -> bool:
            for m in messages:
                if m.get("role") == "tool" and "passed" in (m.get("content") or ""):
                    return True
            return False
        return check


class DependencyUpgradeStrategy:
    def extra_prompt(self) -> str:
        return (
            "## Dependency-upgrade mode\n"
            "Read pyproject.toml / requirements files first.\n"
            "Check the changelog or release notes for the target version.\n"
            "Run the test suite after upgrading. Report any deprecation warnings."
        )

    def tool_subset(self, registry: dict) -> dict:
        return registry

    def success_check(self):
        def check(messages: list[dict]) -> bool:
            for m in messages:
                content = m.get("content") or ""
                if m.get("role") == "tool" and "passed" in content:
                    return True
            return False
        return check
```

### `ProviderCompatibilityStrategy` in depth

Provider-compatibility work — making sure the agent runs correctly on a new model or LiteLLM-proxied backend — has a specific checklist that generic strategies miss. The extra prompt makes that checklist explicit, and the tool subset adds no restrictions because compatibility work touches almost everything.

```python
class ProviderCompatibilityStrategy:
    """Strategy for LiteLLM / model-adapter compatibility tasks.

    This strategy directs the agent to systematically verify four areas:
      1. Adapter tests — does the provider shim behave correctly?
      2. Golden responses — do known prompts still produce matching outputs?
      3. Model config — is the model ID, context window, and tool schema valid?
      4. Retry / fallback behavior — do rate-limit and timeout paths work?
    """

    def extra_prompt(self) -> str:
        return (
            "## Provider-compatibility mode\n\n"
            "You are verifying that this agent works correctly with a new LLM provider "
            "or model identifier routed through LiteLLM.\n\n"
            "Work through these four areas in order:\n\n"
            "### 1. Adapter tests\n"
            "Find and run any tests in `tests/` that exercise `src/provider.py` "
            "or the `stream_response` function. A new provider must pass them all.\n\n"
            "### 2. Golden responses\n"
            "If a `tests/fixtures/golden/` directory (or equivalent) exists, compare "
            "the new provider's output against the stored golden files. Differences in "
            "whitespace or formatting are acceptable; differences in tool-call structure "
            "or finish_reason are not.\n\n"
            "### 3. Model config\n"
            "Check that the model string passed to `litellm.acompletion` is valid: "
            "confirm the context-window size, whether the model supports tool use, "
            "and whether the response format matches OpenAI-style chunks "
            "(buffer `tool_calls` by index, `json.loads` arguments after stream ends).\n\n"
            "### 4. Retry and fallback behavior\n"
            "Check whether `stream_response` handles rate-limit errors (429) and "
            "transient timeouts gracefully. If a fallback model is configured, verify "
            "that LiteLLM's fallback path is exercised and the agent recovers.\n\n"
            "Report findings per area. Do not mark the task done until all four areas pass."
        )

    def tool_subset(self, registry: dict) -> dict:
        return registry  # needs everything: bash for running tests, read_file for configs

    def success_check(self):
        def check(messages: list[dict]) -> bool:
            # All four areas should be mentioned in the final assistant message
            final = next(
                (m["content"] for m in reversed(messages)
                 if m.get("role") == "assistant" and m.get("content")),
                ""
            )
            areas = ["adapter", "golden", "model config", "retry"]
            return all(a in final.lower() for a in areas)
        return check
```

## Trade-offs

| | Benefit | Cost |
|---|---|---|
| **Specialization** | Each task type gets the exact context and constraints it needs | More objects to maintain; classification logic can misfire |
| **Testability** | Each strategy is independently testable | You now test strategies separately from the agent loop |
| **Tool scoping** | A read-only strategy can never call `write_file` | Adds a thin filtering layer; errors if the filter is wrong |
| **Success checks** | Machine-verifiable "done" signal per task | Checks are heuristic — they miss subtle failures |
| **Prompt bloat** | Extra prompt is only present when relevant | Extra prompt still counts against the context window |

The main risk is the classifier (`Strategy.select`) making wrong calls on ambiguous tasks. A task like "update the tests to fix the bug" could match both `BugFixStrategy` and `TestGenerationStrategy`. Mitigations: expose the chosen strategy to the user at the start, make the default strategy permissive (`DefaultStrategy` = no extra prompt, full registry), and let a [Chain of Responsibility](./chain-of-responsibility.md) handler override the choice based on richer signals.

## Related

- [Chain of Responsibility](./chain-of-responsibility.md) — the layer that routes tasks to handlers, which in turn select a strategy.
- [Planner / Executor Split](./planner-executor.md) — a strategy can configure both the planner and executor differently.
- [Skills](../customization/skills.md) — skills are a lightweight, user-facing strategy mechanism; a skill injects extra prompt text the same way `extra_prompt()` does.
- [Prompt Templates](../customization/prompt-templates.md) — the `extra` parameter of `build_system_prompt` is where strategy text lands; prompt templates document the full shape of that parameter.
- [System Prompts](../concepts/system-prompts.md) — background on how `build_system_prompt` is constructed and what the `extra` field may contain.
