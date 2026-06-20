---
sidebar_position: 6
title: Claude CLI Backend
description: Route LLM calls through the `claude -p` CLI instead of LiteLLM by setting USE_CLAUDE_CLI_LLM=1 — use your existing Claude auth, no API key.
---

# Claude CLI Backend

By default the agent reaches the model through `litellm.acompletion` (see
[The Provider Layer](../architecture/provider-layer.md)). Setting the environment variable
**`USE_CLAUDE_CLI_LLM=1`** swaps that for a second backend that shells out to the
[Claude Code CLI](https://docs.claude.com/en/docs/claude-code) in print mode (`claude -p`).

The appeal: `claude -p` uses your **existing Claude login** (subscription or `claude setup-token`),
so the agent runs with **no `ANTHROPIC_API_KEY`** and no per-token API billing — handy for
local development if you already have Claude Code installed.

:::note Status
This is a supported provider-backend design. v1 ships only the LiteLLM path in
`src/provider.py`. The `USE_CLAUDE_CLI_LLM` toggle and the `claude -p` adapter below are the
documented way to add it. The toggle is a plain on/off env var (not part of the `AGENT_*`
settings scheme) because it selects a *backend*, not a tunable.
:::

## How it routes

`stream_response` gains a fork at the top. Everything downstream of it — the agent loop,
streaming accumulation, tool dispatch — is unchanged, because the CLI adapter yields the
**same OpenAI-format chunks** the loop already consumes.

```python
# src/provider.py
import os

USE_CLAUDE_CLI = os.environ.get("USE_CLAUDE_CLI_LLM") == "1"


async def stream_response(messages: list[dict], system_prompt: str):
    if USE_CLAUDE_CLI:
        async for chunk in _claude_cli_stream(messages, system_prompt):
            yield chunk
        return

    # Default: LiteLLM (any provider)
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    response = await litellm.acompletion(
        model=MODEL, messages=full_messages, tools=TOOLS_SCHEMA,
        tool_choice="auto", max_tokens=MAX_TOKENS, stream=True,
    )
    async for chunk in response:
        yield chunk
```

## The `claude -p` adapter

Spawn `claude` in print mode with streaming JSON output, feed it the system prompt and the
latest user turn, and translate its event stream into the chunk shape the loop expects
(`chunk.choices[0].delta.content` + a final `finish_reason`).

```python
# src/provider.py
import asyncio
import json
from types import SimpleNamespace


def _chunk(content=None, finish_reason=None):
    """Mimic one OpenAI-format streaming chunk the agent loop understands."""
    delta = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


async def _claude_cli_stream(messages: list[dict], system_prompt: str):
    prompt = messages[-1]["content"]   # the latest user/tool turn
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", prompt,
        "--system-prompt", system_prompt,
        "--model", MODEL_ALIAS,                 # e.g. "sonnet" / "opus"
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
        # stream-json emits assistant message events with text blocks.
        if event.get("type") == "assistant":
            for block in event["message"]["content"]:
                if block.get("type") == "text":
                    yield _chunk(content=block["text"])
        elif event.get("type") == "result":
            yield _chunk(finish_reason="stop")
    await proc.wait()
```

The CLI flags used here are real (`claude --help`): `-p/--print`, `--system-prompt`,
`--append-system-prompt`, `--model`, `--output-format text|json|stream-json`, and
`--input-format text|stream-json`.

## The tool-calling caveat

This is the part to be honest about. **`claude -p` is itself an agent harness, not a raw
model endpoint.** It runs its own loop with its own built-in tools (and any MCP servers you've
configured for Claude Code). It does **not** accept this project's `TOOLS_SCHEMA` so that *our*
loop can drive *our* seven tools. That breaks the clean separation the LiteLLM path gives you.

You have three honest options:

| Approach | What you get | Cost |
|---|---|---|
| **Text-only backend** | Use `claude -p` purely to generate text turns; disable our tool-calling for CLI runs. | The agent can't use `read_file`/`bash`/etc. — only useful for chat/explanations. |
| **Let Claude Code own the tools** | Pass the task to `claude -p` and let *its* loop read/edit/run. | You're now using Claude Code as the agent; our loop is a thin wrapper. Different architecture. |
| **Translate the stream-json protocol** | Use `--input-format stream-json --output-format stream-json` and map Anthropic `tool_use`/`tool_result` blocks ↔ our OpenAI `tool_calls`/`role:"tool"` messages, restricting Claude's own tools with `--disallowedTools`. | The most work; gives true parity where our loop drives our tools through the CLI's model access. |

The adapter above implements the **text path** (option 1) — enough to prove the routing and
to use your Claude auth for non-tool tasks. For full tool-calling parity, implement option 3:
read `tool_use` blocks out of the `assistant` events and emit them as `delta.tool_calls`
(buffered by index, exactly like [streaming accumulation](../architecture/streaming-and-events.md)),
and write `role:"tool"` results back as `user` `tool_result` blocks on
`--input-format stream-json`.

:::warning
When you hand a task to `claude -p` and let *it* execute tools (option 2), the command runs
with whatever permissions Claude Code is configured for — its own allowlist, not this
project's [Command Allowlist](../operations/command-allowlist.md). Don't assume our gates
apply to commands the CLI runs.
:::

## Enabling it

```bash
# .env (or shell export)
USE_CLAUDE_CLI_LLM=1
```

```bash
# Requires the Claude Code CLI on PATH and a completed login:
claude --version
claude        # one interactive login, or: claude setup-token

uv run main.py "explain what src/agent.py does"
```

No `ANTHROPIC_API_KEY` is needed while the toggle is set — the CLI carries the auth.

## Related pages

- [The Provider Layer](../architecture/provider-layer.md) — the `stream_response` seam this hooks into
- [Custom Providers](./custom-providers.md) — the LiteLLM-based way to add providers
- [Streaming & Event Accumulation](../architecture/streaming-and-events.md) — the chunk shape the adapter must produce
- [Settings Reference](../operations/settings.md) — all environment variables
