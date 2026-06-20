---
sidebar_position: 6
title: "Layer 13.6 — Custom Models & Providers"
description: Swap models and providers by changing the MODEL string or setting USE_CLAUDE_CLI_LLM=1 — the loop stays unchanged.
---

# Layer 13.6 — Custom Models & Providers

:::note Implemented
This step is implemented on branch `step/phase-13-6-models-and-providers` (plan: `plans/tutorial/phase-13-6-models-and-providers.md`).
:::

:::note Starting point
Layer 13.5 complete: MCP servers connect at startup and their tools merge into `TOOLS_SCHEMA`/`TOOL_REGISTRY`. The test suite passes.
:::

The agent loop in `src/agent.py` is provider-agnostic — it calls `stream_response()` and consumes OpenAI-format chunks. The provider choice lives entirely in `src/provider.py`, in two places:

1. The `MODEL` constant — a LiteLLM model string that selects any of 40+ providers by prefix.
2. A `USE_CLAUDE_CLI_LLM` toggle — routes calls through `claude -p` instead of LiteLLM, using your existing Claude login with no API key.

Swapping providers is a configuration change, not a code change. The loop, tools, and prompt are unchanged.

The model reference table and per-task selection patterns are in [Custom Models](../../customization/custom-models.md). The LiteLLM prefix routing and local endpoints are in [Custom Providers](../../customization/custom-providers.md). The CLI backend is in [Claude CLI Backend](../../customization/claude-cli-backend.md).

## What you'll learn

- How the `MODEL` string prefix selects a LiteLLM provider (no prefix = Anthropic, `gemini/` = Google, `ollama/` = local, etc.).
- How to expose `--model` and `MODEL` env var overrides without touching the loop.
- How `USE_CLAUDE_CLI_LLM=1` forks `stream_response` to shell out to `claude -p`.
- The honest tradeoff: the CLI backend only supports text-only tasks in its base form (no TOOLS_SCHEMA forwarding).

## Build it

### Step 1 — Make `MODEL` configurable via env var

`src/provider.py` currently has `MODEL` hardcoded. Read it from the environment so it's overridable without editing source:

```python
# src/provider.py
import os
import litellm

MODEL = os.environ.get("AGENT_MODEL", "claude-sonnet-4-5")
MAX_TOKENS = int(os.environ.get("AGENT_MAX_TOKENS", "8096"))

from tools import TOOLS_SCHEMA


async def stream_response(
    messages: list[dict],
    system_prompt: str,
    model: str | None = None,
):
    effective_model = model or MODEL
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    response = await litellm.acompletion(
        model=effective_model,
        messages=full_messages,
        tools=TOOLS_SCHEMA,
        tool_choice="auto",
        max_tokens=MAX_TOKENS,
        stream=True,
    )
    async for chunk in response:
        yield chunk
```

No loop change required — `stream_response` already yields OpenAI-format chunks.

### Step 2 — Add the `USE_CLAUDE_CLI_LLM` fork

When `USE_CLAUDE_CLI_LLM=1`, `stream_response` shells out to `claude -p` instead of calling LiteLLM. Everything downstream — streaming accumulation, tool dispatch, message history — is unchanged because the adapter yields the same chunk shape.

```python
# src/provider.py (updated)
import asyncio
import json
import os
from types import SimpleNamespace

import litellm

from tools import TOOLS_SCHEMA

MODEL = os.environ.get("AGENT_MODEL", "claude-sonnet-4-5")
MAX_TOKENS = int(os.environ.get("AGENT_MAX_TOKENS", "8096"))
USE_CLAUDE_CLI = os.environ.get("USE_CLAUDE_CLI_LLM") == "1"
# Short alias accepted by claude -p (e.g. "sonnet", "opus")
MODEL_ALIAS = os.environ.get("AGENT_CLI_MODEL_ALIAS", "sonnet")


def _chunk(content=None, finish_reason=None):
    """Mimic one OpenAI-format streaming chunk."""
    delta = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


async def _claude_cli_stream(messages: list[dict], system_prompt: str):
    """Yield text chunks from claude -p (text-only; no TOOLS_SCHEMA forwarding)."""
    prompt = messages[-1]["content"]
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", prompt,
        "--system-prompt", system_prompt,
        "--model", MODEL_ALIAS,
        "--output-format", "stream-json",
        "--verbose",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    async for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        event = json.loads(line)
        if event.get("type") == "assistant":
            for block in event["message"]["content"]:
                if block.get("type") == "text":
                    yield _chunk(content=block["text"])
        elif event.get("type") == "result":
            yield _chunk(finish_reason="stop")
    await proc.wait()


async def stream_response(
    messages: list[dict],
    system_prompt: str,
    model: str | None = None,
):
    if USE_CLAUDE_CLI:
        async for chunk in _claude_cli_stream(messages, system_prompt):
            yield chunk
        return

    # Default: LiteLLM — any of 40+ providers via MODEL prefix
    effective_model = model or MODEL
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    response = await litellm.acompletion(
        model=effective_model,
        messages=full_messages,
        tools=TOOLS_SCHEMA,
        tool_choice="auto",
        max_tokens=MAX_TOKENS,
        stream=True,
    )
    async for chunk in response:
        yield chunk
```

:::warning CLI backend is text-only in this form
`claude -p` is itself an agent harness. It does not accept this project's `TOOLS_SCHEMA`, so the built-in tools are unavailable when `USE_CLAUDE_CLI_LLM=1`. The CLI backend is useful for text-only tasks (explanations, summaries, Q&A) and for running the agent without an API key. For full tool-calling parity, see the [Claude CLI Backend](../../customization/claude-cli-backend.md#the-tool-calling-caveat) page — option 3 (translate the stream-json protocol) is the full solution.
:::

### Step 3 — Expose `--model` in `main.py`

```python
# main.py (updated)
import argparse
import asyncio
import os
import sys

from src.agent import run_agent
from src.mcp_client import load_mcp_servers
from src.project_instructions import load_project_instructions
from src.prompts import build_system_prompt
from src.skills import ACTIVE_SKILLS


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", nargs="+")
    parser.add_argument("--model", default=None, help="LiteLLM model string override")
    parser.add_argument("--skills", nargs="*", default=None, metavar="SKILL")
    args = parser.parse_args()

    task = " ".join(args.task)
    cwd = os.getcwd()
    active_skills = args.skills if args.skills is not None else ACTIVE_SKILLS

    sessions = await load_mcp_servers()
    try:
        extra = load_project_instructions(cwd)
        system_prompt = build_system_prompt(cwd=cwd, extra=extra, skills=active_skills)
        await run_agent(task, system_prompt=system_prompt, model=args.model)
    finally:
        for session in sessions:
            await session.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

Pass `model` through to `run_agent`, which passes it to `stream_response`:

```python
# src/agent.py — run_agent signature
async def run_agent(
    task: str,
    system_prompt: str | None = None,
    model: str | None = None,
    before_tool_call=None,
    after_tool_call=None,
) -> list[dict]:
    ...
    # Inside the loop, pass model to stream_response:
    async for chunk in stream_response(messages, system_prompt, model=model):
        ...
```

### Provider reference

| `MODEL` string | Provider | Auth env var |
|---|---|---|
| `claude-sonnet-4-5` | Anthropic (default) | `ANTHROPIC_API_KEY` |
| `claude-opus-4-5` | Anthropic | `ANTHROPIC_API_KEY` |
| `gpt-4o` | OpenAI | `OPENAI_API_KEY` |
| `gemini/gemini-2.0-flash` | Google Gemini | `GEMINI_API_KEY` |
| `ollama/llama3.2` | Local Ollama | none |
| `openai/my-model` + `api_base` | Any OpenAI-compatible | `OPENAI_API_KEY` |
| `bedrock/claude-sonnet-4-5` | AWS Bedrock | `AWS_*` |

Set credentials in `.env` at the repo root. `python-dotenv` loads them at startup in `main.py`:

```python
from dotenv import load_dotenv
load_dotenv()
```

See [Custom Providers](../../customization/custom-providers.md) for the full routing table and local endpoint configuration.

## Test it

### Behavior (BDD)

Verify this layer as a **BDD gate** — run the scenario below twice:

1. **Before verification (red):** run it *before* the *Build it* code — it must **fail**, naming the requirement that isn't met yet.
2. **After verification (green):** run it *after* the *Build it* code — it must **pass**, proving the requirement is now met.

```gherkin
Scenario: Changing MODEL routes to a different provider; USE_CLAUDE_CLI_LLM routes via claude -p
  Given the default MODEL is "claude-sonnet-4-5"
  When stream_response is called with model="gpt-4o"
  Then litellm.acompletion is called with model="gpt-4o"
  And the agent loop receives the same OpenAI-format chunk stream
  And the tool dispatch and message history are unchanged

  Given USE_CLAUDE_CLI_LLM=1 is set in the environment
  When stream_response is called
  Then _claude_cli_stream is called instead of litellm.acompletion
  And a claude subprocess is spawned with the -p flag
  And text chunks from the CLI are yielded in the same OpenAI-format shape
```

Run this as an integration scenario with the [BDD framework](../../guides/bdd-integration-testing.md).

The scenario fails before the change because `MODEL` is hardcoded (the `model` argument to `stream_response` is ignored), and `USE_CLAUDE_CLI_LLM` has no effect. After the change, the `model` override routes the LiteLLM call correctly, and the CLI fork spawns `claude -p`.

### Existing tests

```bash
uv run pytest -q
```

With no env var overrides, `MODEL` resolves to `"claude-sonnet-4-5"` (the original default) and `USE_CLAUDE_CLI` is `False`. Test mocks of `litellm.acompletion` continue to work.

## Run it

```bash
# Default: claude-sonnet-4-5
uv run main.py "list the files in src/"

# Switch to OpenAI — no loop change needed
AGENT_MODEL=gpt-4o uv run main.py "add type hints to tools.py"

# Per-invocation override
uv run main.py --model gemini/gemini-2.0-flash "explain the agent loop"

# Local Ollama (no API key)
AGENT_MODEL=ollama/llama3.2 uv run main.py "summarize this repo"

# Claude CLI backend — uses your Claude login, no ANTHROPIC_API_KEY
USE_CLAUDE_CLI_LLM=1 uv run main.py "explain what src/agent.py does"
```

:::tip Architecture pattern
Swapping providers behind `stream_response` is [Ports & Adapters](../../architecture-patterns/ports-and-adapters.md): one `LLMPort`, interchangeable adapters.
:::

## Recap

The provider layer in `src/provider.py` is the only file that needs to change for a provider swap. Two levers:

- **`AGENT_MODEL` / `--model`** selects any LiteLLM-supported provider via the model string prefix. The loop, tools, prompt, and MCP integration are completely unaware of the switch.
- **`USE_CLAUDE_CLI_LLM=1`** forks `stream_response` to shell out to `claude -p`, yielding the same chunk shape. Useful for running without an API key on text-only tasks.

Phase 13 is complete. The agent now has project context (AGENTS.md), composable skills, hook points, a growing tool registry via MCP, and a swappable provider layer. All of these layers stack — each is independently configurable and none requires changes to the core loop.

The next phase wires the agent into programmatic interfaces: the Anthropic SDK agent harness and a server that accepts tasks over HTTP.

→ [Phase 14 — Interface It](../14-interface-it/1-sdk.md)
