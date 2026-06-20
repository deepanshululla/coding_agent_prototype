"""The provider layer — a single async streaming call over LiteLLM.

LiteLLM replaces pi's 40+ hand-written provider adapters: it normalizes every provider to
the OpenAI chunk format, so the agent loop only ever speaks one dialect. Swap providers by
changing :data:`MODEL` (the prefix selects the provider) — ``claude-sonnet-4-5`` →
Anthropic, ``gemini/gemini-2.0-flash`` → Google, ``gpt-4o`` → OpenAI. The matching API key
is read from the environment (e.g. ``ANTHROPIC_API_KEY``); no explicit client setup needed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import litellm

from tools import TOOLS_SCHEMA

MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 8096


async def stream_response(
    messages: list[dict], system_prompt: str
) -> AsyncIterator[Any]:
    """Stream a model response as OpenAI-format chunks.

    ``acompletion`` is non-blocking, so the event loop stays free to execute tools
    concurrently while tokens arrive. Yields chunks unchanged for the agent loop to
    accumulate.
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
