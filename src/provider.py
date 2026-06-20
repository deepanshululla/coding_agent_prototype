from __future__ import annotations

import asyncio

MODEL_ALIAS = "sonnet"  # passed to claude --model; change to "opus" etc.


class ModelClient:
    """Wraps `claude -p` to make a single non-streaming completion call."""

    async def complete(self, messages: list[dict], system_prompt: str) -> str:
        """Run claude -p with the latest user message and return the reply text."""
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


# Module singleton — everything outside provider.py imports this function only.
_client = ModelClient()


async def call_model(messages: list[dict], system_prompt: str) -> str:
    """Send messages to the model and return the reply text.

    Delegates to the ModelClient singleton. Callers never instantiate the class.
    Phase 3 renames this to stream_response and makes it an async generator.
    Phase 11 swaps the class body to LiteLLM without changing this signature.
    """
    return await _client.complete(messages, system_prompt)
