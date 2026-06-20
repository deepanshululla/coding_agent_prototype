"""The agent: a nested outer/inner loop.

- The **inner loop** is the agent proper: stream a response, execute any requested tool
  calls in parallel, append the results, and go again — until the model returns text with
  no tool calls (``finish_reason == "stop"``).
- The **outer loop** re-enters only when follow-up ("steering") messages were queued after
  the agent would otherwise have stopped.

Streaming note: tool-call arguments arrive as **partial JSON strings** spread across
chunks. We buffer fragments by ``index`` and ``json.loads`` only once the stream ends.
"""

from __future__ import annotations

import asyncio
import json

from prompts import build_system_prompt
from provider import stream_response
from tools import TOOL_REGISTRY
from types_ import ToolResult

MAX_ITERATIONS = 30


async def run_agent(task: str) -> list[dict]:
    """Run the agent to completion on ``task``. Returns the final message history."""
    system_prompt = build_system_prompt()
    messages: list[dict] = [{"role": "user", "content": task}]
    pending_messages: list[dict] = []

    # OUTER LOOP: re-enter if follow-up messages arrive after the agent finishes.
    while True:
        has_more_tool_calls = True
        iteration = 0

        # INNER LOOP: the tool-call cycle.
        while (has_more_tool_calls or pending_messages) and iteration < MAX_ITERATIONS:
            iteration += 1

            if pending_messages:
                messages.extend(pending_messages)
                pending_messages.clear()

            # ── Phase A: Stream from the model ───────────────────────────────
            text_buf = ""
            tool_acc: dict[int, dict] = {}  # index → {id, name, arguments_buf}
            finish_reason = None

            async for chunk in stream_response(messages, system_prompt):
                choice = chunk.choices[0]
                delta = choice.delta
                finish_reason = choice.finish_reason or finish_reason

                if getattr(delta, "content", None):
                    text_buf += delta.content
                    print(delta.content, end="", flush=True)

                for tc_chunk in getattr(delta, "tool_calls", None) or []:
                    idx = tc_chunk.index
                    slot = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments_buf": ""})
                    if tc_chunk.id:
                        slot["id"] = tc_chunk.id
                    fn = getattr(tc_chunk, "function", None)
                    if fn and fn.name:
                        slot["name"] = fn.name
                        print(f"\n▸ {fn.name}", end="", flush=True)
                    if fn and fn.arguments:
                        slot["arguments_buf"] += fn.arguments

            print()  # newline after the streamed turn

            # Finalize tool calls (arguments stay a JSON *string* in history).
            tool_calls = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments_buf"]},
                }
                for tc in tool_acc.values()
            ]

            # ── Phase B: Append the assistant turn to history ────────────────
            assistant_msg: dict = {"role": "assistant", "content": text_buf or None}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            # ── Phase C: Stop check ──────────────────────────────────────────
            if not tool_calls:
                has_more_tool_calls = False
                continue

            # ── Phase D: Execute tool calls in parallel ──────────────────────
            parsed_calls = [
                {
                    "id": tc["id"],
                    "name": tc["function"]["name"],
                    "input": json.loads(tc["function"]["arguments"] or "{}"),
                }
                for tc in tool_calls
            ]
            results = await _execute_tools_parallel(parsed_calls)

            # ── Phase E: Push tool results (one "tool" message each) ─────────
            for r in results:
                messages.append(
                    {"role": "tool", "tool_call_id": r.tool_call_id, "content": r.content}
                )

        break  # no follow-up source wired in v1; outer loop runs once

    return messages


async def _execute_tools_parallel(tool_calls: list[dict]) -> list[ToolResult]:
    """Run every tool call concurrently and collect results in order."""
    return await asyncio.gather(*(_execute_one_tool(tc) for tc in tool_calls))


async def _execute_one_tool(tool_call: dict) -> ToolResult:
    name = tool_call["name"]
    args = tool_call["input"]
    print(f"  [executing {name} {args}]")
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
    try:
        result = await fn(**args)
    except Exception as e:  # tools shouldn't raise, but never let one kill the loop
        return ToolResult(tool_call["id"], name, f"Error: {e}", is_error=True)
    print(f"  [✓ {name}: {len(result)} chars]")
    return ToolResult(tool_call["id"], name, result)
