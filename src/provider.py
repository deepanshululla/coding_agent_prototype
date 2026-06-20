from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

MODEL_ALIAS = "sonnet"  # passed to claude --model; change to "opus" etc.


def _chunk(content=None, finish_reason=None):
    """Build one OpenAI-format streaming chunk the agent loop understands.

    Uses SimpleNamespace so no provider SDK is needed. Phase 11 replaces the
    class body with litellm.acompletion, which returns real chunk objects with
    this same shape.
    """
    delta = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


class ModelClient:
    """Wraps `claude -p` as a streaming completion backend."""

    async def complete(self, messages: list[dict], system_prompt: str) -> str:
        """Non-streaming path (kept for reference; loop uses stream() from Phase 3 on)."""
        prompt = messages[-1]["content"]
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", prompt,
            "--system-prompt", system_prompt,
            "--model", MODEL_ALIAS,
            "--output-format", "text",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode().strip()

    async def stream(
        self, messages: list[dict], system_prompt: str
    ) -> AsyncIterator[Any]:
        """Stream via `claude -p --output-format stream-json`.

        Translates CLI events into OpenAI-format chunks so the agent loop
        sees the same interface regardless of backend.
        """
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
        async for raw_line in proc.stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            # stream-json emits assistant events with text blocks.
            if event.get("type") == "assistant":
                for block in event["message"]["content"]:
                    if block.get("type") == "text":
                        yield _chunk(content=block["text"])
            elif event.get("type") == "result":
                yield _chunk(finish_reason="stop")
        await proc.wait()


# Module singleton — everything outside provider.py imports the functions only.
_client = ModelClient()


async def call_model(messages: list[dict], system_prompt: str) -> str:
    """Non-streaming call — kept so Phase 1/2 code still works.

    Delegates to the ModelClient singleton. Callers never instantiate the class.
    """
    return await _client.complete(messages, system_prompt)


async def stream_response(
    messages: list[dict], system_prompt: str
) -> AsyncIterator[Any]:
    """Stream a model response as OpenAI-format chunks.

    This is the function the agent loop imports from Phase 3 onward. The
    underlying backend (claude -p now; LiteLLM in Phase 11) is hidden behind
    ModelClient — the signature and chunk shape never change.
    """
    async for chunk in _client.stream(messages, system_prompt):
        yield chunk
