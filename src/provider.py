from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import litellm

from tools import TOOLS_SCHEMA

MODEL = "claude-sonnet-4-5"  # prefix selects provider; change to swap (e.g. "gpt-4o")
MAX_TOKENS = 8096


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
    messages: list[dict], system_prompt: str
) -> AsyncIterator[Any]:
    """Stream a model response as OpenAI-format chunks.

    acompletion is non-blocking, so the event loop stays free to execute tools
    concurrently while tokens arrive. Yields chunks unchanged for the agent loop
    to accumulate. The backend is LiteLLM (Phase 11); the model string in MODEL
    routes to the matching provider via its prefix, picking up the API key from
    the environment automatically. The signature and chunk shape are the same
    the loop has consumed since Phase 3.
    """
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    response = await litellm.acompletion(
        model=MODEL,
        messages=full_messages,
        tools=TOOLS_SCHEMA,
        tool_choice="auto",
        max_tokens=MAX_TOKENS,
        stream=True,
    )
    async for chunk in response:
        yield chunk
