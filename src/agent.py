from __future__ import annotations

import asyncio
import json

from prompts import build_system_prompt
from provider import stream_response
from renderer import emit
from tools import TOOL_REGISTRY
from types_ import ToolResult

MAX_ITERATIONS = 30


async def run_agent(task: str) -> list[dict]:
    """Run the agent on task and return the final message history.

    Phase 4: text + one tool. The inner loop streams a model turn, appends the
    assistant message (carrying tool_calls when present), and — if the model
    requested tools — dispatches them and injects each result as a role:"tool"
    message before looping back to the model. A plain text turn ends the loop.
    """
    system_prompt = build_system_prompt()
    messages: list[dict] = [{"role": "user", "content": task}]

    # OUTER LOOP: re-enters if follow-up messages arrive. Runs once for now.
    while True:
        has_more_tool_calls = True
        iteration = 0

        # INNER LOOP: the tool-call cycle.
        while has_more_tool_calls and iteration < MAX_ITERATIONS:
            iteration += 1

            # ── Phase A: stream the model response, accumulating as we go. ──
            text_buf = ""
            tool_acc: dict[int, dict] = {}
            finish_reason = None

            async for chunk in stream_response(
                messages=messages,
                system_prompt=system_prompt,
            ):
                choice = chunk.choices[0]
                delta = choice.delta
                # Carry the last non-None finish_reason forward.
                finish_reason = choice.finish_reason or finish_reason

                if getattr(delta, "content", None):
                    text_buf += delta.content
                    emit({"type": "text_delta", "delta": delta.content})

                for tc_chunk in getattr(delta, "tool_calls", None) or []:
                    idx = tc_chunk.index
                    slot = tool_acc.setdefault(
                        idx, {"id": "", "name": "", "arguments_buf": ""}
                    )
                    if tc_chunk.id:
                        slot["id"] = tc_chunk.id
                    fn = getattr(tc_chunk, "function", None)
                    if fn and fn.name:
                        slot["name"] = fn.name
                        emit({"type": "tool_call_start", "index": idx,
                              "tool_call_id": slot["id"], "name": fn.name})
                    if fn and fn.arguments:
                        slot["arguments_buf"] += fn.arguments

            emit({"type": "turn_end", "iteration": iteration,
                  "finish_reason": finish_reason or "stop",
                  "tool_calls_count": len(tool_acc)})

            # Finalize tool calls (arguments stay a JSON string in history).
            tool_calls = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments_buf"],
                    },
                }
                for tc in tool_acc.values()
            ]

            # ── Phase B: append the assistant turn. ────────────────────────
            # Must include tool_calls (even with empty content) or the provider
            # rejects the next request as malformed.
            assistant_msg: dict = {"role": "assistant", "content": text_buf or None}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            # ── Phase C: stop check — a turn with no tools means we are done. ──
            if not tool_calls:
                has_more_tool_calls = False
                continue

            # ── Phase D: parse and dispatch the requested tools. ───────────
            parsed_calls = [
                {
                    "id": tc["id"],
                    "index": i,
                    "name": tc["function"]["name"],
                    "input": json.loads(tc["function"]["arguments"] or "{}"),
                }
                for i, tc in enumerate(tool_calls)
            ]
            results = await _execute_tools_parallel(parsed_calls)

            # ── Phase E: push one role:"tool" message per result. ──────────
            for r in results:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": r.tool_call_id,
                        "content": r.content,
                    }
                )

        break  # outer loop: no follow-up support yet

    emit({"type": "agent_end", "total_iterations": iteration, "status": "ok"})
    return messages


async def _execute_tools_parallel(tool_calls: list[dict]) -> list[ToolResult]:
    """Run every requested tool concurrently and gather their results in order."""
    return await asyncio.gather(*(_execute_one_tool(tc) for tc in tool_calls))


async def _execute_one_tool(tool_call: dict) -> ToolResult:
    """Look up one tool by name, call it, and wrap the outcome in a ToolResult.

    Both an unknown tool and an exception become an is_error result rather than
    propagating — the loop keeps running and the model can read the error.
    """
    name = tool_call["name"]
    args = tool_call["input"]
    # tool_call_start was already emitted during streaming; no event here.
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        emit({"type": "tool_call_end", "index": tool_call.get("index", 0),
              "tool_call_id": tool_call["id"], "name": name,
              "content": f"Unknown tool: {name}", "is_error": True, "chars": 0})
        return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
    try:
        result = await fn(**args)
    except Exception as e:
        emit({"type": "tool_call_end", "index": tool_call.get("index", 0),
              "tool_call_id": tool_call["id"], "name": name,
              "content": f"Error: {e}", "is_error": True, "chars": 0})
        return ToolResult(tool_call["id"], name, f"Error: {e}", is_error=True)
    emit({"type": "tool_call_end", "index": tool_call.get("index", 0),
          "tool_call_id": tool_call["id"], "name": name,
          "content": result, "is_error": False, "chars": len(result)})
    return ToolResult(tool_call["id"], name, result)
