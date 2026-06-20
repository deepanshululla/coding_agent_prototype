---
sidebar_position: 3
title: Ports & Adapters (Hexagonal)
description: Keep the agent core independent of providers, repositories, and storage backends by defining typed ports and swapping adapters without changing a line of core logic.
---

# Ports & Adapters (Hexagonal)

The agent core — the loop, the planner, the tool dispatcher — should be oblivious to whether it's talking to Claude or GPT-4, reading from GitHub or GitLab, or storing memory in Postgres or a local file. Ports & Adapters (also called Hexagonal Architecture) is the pattern that enforces that ignorance. Your project already demonstrates it at the LLM boundary; this page shows you how to complete the picture.

## The problem

Left ungoverned, a coding agent accretes provider-specific logic. The LLM streaming loop learns about Anthropic's `stop_reason` field. The `bash` tool hard-codes a local subprocess. The memory store is a JSON file the tests depend on existing. When you want to:

- swap Anthropic for OpenAI during an outage
- run the agent against a local git mirror instead of GitHub
- test the loop with a scripted LLM that returns deterministic responses
- isolate agent edits in a git worktree so they can't corrupt the working tree

…you discover that the core and the infrastructure are intertwined and none of that is easy.

## The pattern

Define **ports**: typed interfaces (Python `Protocol`s) that describe what the core needs from the outside world, expressed in the agent's vocabulary — not the provider's.

Write **adapters**: concrete implementations of each port that talk to a specific provider (LiteLLM, GitHub API, Postgres, a subprocess sandbox). The core never imports an adapter directly; it receives an adapter instance through its constructor or function arguments.

```
         ┌──────────────────────────────────────┐
         │            Agent Core                │
         │  run_agent()  _execute_one_tool()    │
         │                                      │
         │  speaks only the Port interfaces     │
         └───┬──────┬──────┬────────┬───────────┘
             │      │      │        │
          LLMPort RepoPort ToolPort MemoryPort  SandboxPort
             │      │      │        │
    ┌────────┘  ┌───┘   ┌──┘    ┌───┘
    │           │       │       │
LiteLLM   GitHubAdapter  PluginRegistry  FileMemory
adapter   GitLabAdapter               PostgresMemory
ScriptedLLM (tests)                   (tests: dict)
```

Adapters live outside the core. Tests replace real adapters with fakes. Switching providers means swapping one adapter object.

## In this project

`provider.py` is **already a `LLMPort`** — and the project demonstrates two adapters for it without naming them that way.

`stream_response` in `provider.py` wraps `litellm.acompletion`. LiteLLM is the adapter: it normalises Anthropic, OpenAI, Gemini, Cohere, and every other provider to a single OpenAI-format chunk stream. The agent loop in `agent.py` never knows which provider is behind the chunks — it just iterates:

```python
# src/agent.py — the core consumes the port, not the adapter
async for chunk in stream_response(messages, system_prompt):
    choice = chunk.choices[0]
    delta = choice.delta
    ...
```

The [Claude CLI backend](../customization/claude-cli-backend.md) is a second adapter: it routes the same `stream_response` signature to the `claude` CLI process instead of to LiteLLM. The core doesn't change.

:::note Planned pattern, not yet shipped
The `LLMPort` is implicit today — `stream_response` is a module-level function rather than an injected object. The protocols below show how to make the boundary explicit. `ScriptedLLM` (the test double referenced below) is planned for the test suite.
:::

**Define the ports as Protocols**

```python
# src/ports.py
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMPort(Protocol):
    """Stream a model response as OpenAI-format chunks."""

    async def stream(
        self, messages: list[dict], system_prompt: str
    ) -> AsyncIterator[Any]:
        ...


@runtime_checkable
class RepoPort(Protocol):
    """Read and write source code in a repository."""

    async def read_file(self, path: str) -> str: ...
    async def write_file(self, path: str, content: str) -> str: ...
    async def run_command(self, command: str) -> str: ...


@runtime_checkable
class MemoryPort(Protocol):
    """Persist and retrieve agent state across turns."""

    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str) -> None: ...


@runtime_checkable
class SandboxPort(Protocol):
    """Execute shell commands in an isolated environment."""

    async def run(self, command: str, timeout: int = 30) -> str: ...
```

**The LiteLLM adapter (already in `provider.py`)**

```python
# src/adapters/litellm_adapter.py
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import litellm

from src.tools import TOOLS_SCHEMA

MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 8096


class LiteLLMAdapter:
    """Wraps litellm.acompletion as an LLMPort."""

    def __init__(self, model: str = MODEL) -> None:
        self.model = model

    async def stream(
        self, messages: list[dict], system_prompt: str
    ) -> AsyncIterator[Any]:
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        response = await litellm.acompletion(
            model=self.model,
            messages=full_messages,
            tools=TOOLS_SCHEMA,
            tool_choice="auto",
            max_tokens=MAX_TOKENS,
            stream=True,
        )
        async for chunk in response:
            yield chunk
```

This is exactly what `stream_response` in `provider.py` does today — wrapping it in a class makes the `LLMPort` interface explicit.

**A scripted LLM adapter for tests**

```python
# tests/fakes.py
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any


class ScriptedLLM:
    """Returns pre-baked responses without any network call.

    Pass a list of response dicts; the adapter cycles through them
    one per call to stream().
    """

    def __init__(self, responses: list[list[dict]]) -> None:
        self._queue = list(responses)

    async def stream(
        self, messages: list[dict], system_prompt: str
    ) -> AsyncIterator[Any]:
        if not self._queue:
            raise RuntimeError("ScriptedLLM exhausted")
        chunks = self._queue.pop(0)
        for chunk in chunks:
            yield chunk
```

Inject it into `run_agent` instead of the real adapter and your test suite never makes a network call:

```python
# tests/test_agent.py
from tests.fakes import ScriptedLLM

async def test_agent_calls_read_file():
    llm = ScriptedLLM(responses=[
        [make_tool_call_chunk("read_file", {"path": "README.md"})],
        [make_stop_chunk("Here is the file content.")],
    ])
    await run_agent("summarise README.md", llm=llm)
    # assert history, tool calls, etc.
```

**A GitHub adapter for `RepoPort`**

```python
# src/adapters/github_adapter.py
import httpx
from src.ports import RepoPort   # type: ignore[misc]  — Protocol


class GitHubAdapter:
    """Reads files from a GitHub repository via the REST API."""

    def __init__(self, token: str, repo: str) -> None:
        self._token = token
        self._repo = repo

    async def read_file(self, path: str) -> str:
        url = f"https://api.github.com/repos/{self._repo}/contents/{path}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, headers={"Authorization": f"Bearer {self._token}"}
            )
        if resp.status_code == 404:
            return f"Error: file not found: {path}"
        resp.raise_for_status()
        import base64
        return base64.b64decode(resp.json()["content"]).decode()

    async def write_file(self, path: str, content: str) -> str:
        # PUT to GitHub contents API (omitted for brevity)
        ...

    async def run_command(self, command: str) -> str:
        return "Error: shell commands not supported on a remote repo"
```

Swap in `LocalRepoAdapter` (which calls `subprocess`) for local development, `GitHubAdapter` for CI, `GitLabAdapter` if your team runs GitLab — the core doesn't change.

**Wiring adapters into the core**

```python
# src/agent.py  (updated signature)
async def run_agent(
    task: str,
    *,
    llm: LLMPort | None = None,
    repo: RepoPort | None = None,
) -> list[dict]:
    llm = llm or LiteLLMAdapter()
    repo = repo or LocalRepoAdapter()
    ...
    async for chunk in llm.stream(messages, system_prompt):
        ...
```

Production code uses the real adapters (default). Tests inject fakes. No monkey-patching, no `unittest.mock.patch`.

## Trade-offs

| | Ports & Adapters | Direct imports |
|---|---|---|
| **Testability** | Inject fakes; zero network in tests | Must mock module-level functions |
| **Provider swap** | Change one argument at the call site | Edit import and possibly the call signature |
| **Readability** | Explicit dependencies, clear seams | Simple module-level calls |
| **Boilerplate** | Protocol classes + adapter wrappers | None |
| **Right time to adopt** | When you have (or plan) >1 provider, or need testable integration tests | Single provider, small codebase, mocking is acceptable |

The `LLMPort` is the highest-value port to introduce first — the test suite is what drives the need most visibly. `SandboxPort` follows closely because it gates the [worktree isolation](./worktrees.md) pattern: the sandbox adapter decides whether `bash` calls go to a subprocess, a Docker container, or an in-process mock.

## Related

- [Provider layer](../architecture/provider-layer.md)
- [Custom providers](../customization/custom-providers.md)
- [Claude CLI backend](../customization/claude-cli-backend.md)
- [Plugin Architecture](./plugin-architecture.md)
- [Worktrees](./worktrees.md)
