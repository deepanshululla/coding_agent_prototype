from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import litellm

from config import MAX_TOKENS, MODEL
from tools import TOOLS_SCHEMA

# Phase 13.6: an opt-in fork that shells out to `claude -p` instead of LiteLLM.
# Set USE_CLAUDE_CLI_LLM=1 to route stream_response through the local Claude CLI
# (text-only — TOOLS_SCHEMA is not forwarded). Any other value keeps the LiteLLM
# path. MODEL / MAX_TOKENS are read from the environment via config (AGENT_MODEL,
# AGENT_MAX_TOKENS), so the provider is configurable without touching this file.
USE_CLAUDE_CLI = os.environ.get("USE_CLAUDE_CLI_LLM", "") == "1"


def _chunk(content=None, finish_reason=None, tool_calls=None):
    """Build one OpenAI-format streaming chunk the agent loop understands.

    Uses SimpleNamespace so no provider SDK is needed in tests. litellm yields
    real chunk objects with this same shape, so the loop — and the test harness
    that scripts these chunks — sees one interface regardless of backend.
    tool_calls carries a list of streamed tool-call fragments, each shaped like
    _tc() below.
    """
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


def _tc(index, id=None, name=None, arguments=None):
    """Build one OpenAI-format tool-call delta fragment for a streaming chunk.

    Mirrors the shape litellm yields in delta.tool_calls: an .index, an .id,
    and a nested .function with .name and .arguments. A whole call may arrive in
    one fragment, or .arguments may be split across fragments.
    """
    function = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=id, function=function)


async def stream_response(
    messages: list[dict], system_prompt: str, model: str | None = None
) -> AsyncIterator[Any]:
    """Stream a model response as OpenAI-format chunks.

    acompletion is non-blocking, so the event loop stays free to execute tools
    concurrently while tokens arrive. Yields chunks unchanged for the agent loop
    to accumulate. The backend is LiteLLM (Phase 11); the model string routes to
    the matching provider via its prefix, picking up the API key from the
    environment automatically. The signature and chunk shape are the same the
    loop has consumed since Phase 3.

    model (Phase 13.6), when provided, overrides the module-level MODEL for this
    one turn — this is how the `--model` CLI flag selects a provider per run.
    When None (the default) MODEL is used, so existing callers are unaffected.

    When USE_CLAUDE_CLI is set (USE_CLAUDE_CLI_LLM=1), the LiteLLM call is
    skipped entirely and the turn is served by `claude -p` via _claude_cli_stream
    — a text-only fork that still yields the same OpenAI-format chunk shape.
    """
    effective_model = model or MODEL

    if USE_CLAUDE_CLI:
        async for chunk in _claude_cli_stream(messages, system_prompt, effective_model):
            yield chunk
        return

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


def _messages_to_prompt(system_prompt: str, messages: list[dict]) -> str:
    """Flatten the system prompt + message history into one text prompt.

    `claude -p` takes a single prompt string, not a structured message list, so
    we render the conversation as labelled turns. Tool messages are folded in as
    plain text — this fork is text-only, so there is no tool_calls structure to
    preserve, just the content the model needs to read.
    """
    parts = [f"System: {system_prompt}"]
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content") or ""
        parts.append(f"{role.capitalize()}: {content}")
    return "\n\n".join(parts)


async def _claude_cli_stream(
    messages: list[dict], system_prompt: str, model: str | None = None
) -> AsyncIterator[Any]:
    """Serve one turn by shelling out to `claude -p`, yielding OpenAI chunks.

    A subprocess runs the local Claude CLI in print mode (-p), streaming its
    stdout line by line. Each line becomes a text_delta chunk shaped exactly like
    the LiteLLM path's chunks, so the agent loop never knows the backend changed.
    A final empty chunk carries finish_reason="stop" to close the turn.

    Text-only: TOOLS_SCHEMA is not forwarded, so the CLI cannot call tools in
    this fork. Full tool-calling parity needs the stream-json protocol (deferred).
    """
    prompt = _messages_to_prompt(system_prompt, messages)
    cmd = ["claude", "-p", prompt]
    if model:
        cmd += ["--model", model]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        yield _chunk(content=line.decode(errors="replace"))

    await proc.wait()
    # Close the turn so the loop's finish_reason check fires (no tool calls).
    yield _chunk(finish_reason="stop")
