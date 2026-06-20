from __future__ import annotations

import asyncio
import json

from allowlist import check_command
from prompts import build_system_prompt
from provider import stream_response
from renderer import emit
from tools import TOOL_REGISTRY
from types_ import ToolResult

MAX_ITERATIONS = 30


async def run_agent(
    task: str,
    pending_messages: list[dict] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> list[dict]:
    """Run the agent on task and return the final message history.

    Phase 4: text + one tool. The inner loop streams a model turn, appends the
    assistant message (carrying tool_calls when present), and — if the model
    requested tools — dispatches them and injects each result as a role:"tool"
    message before looping back to the model. A plain text turn ends the loop.

    pending_messages, when provided (Phase 10.4), is a shared list that the TUI
    input box appends to; the outer loop reads from it for steering follow-ups.
    When None (the default), a fresh empty list is used so existing callers and
    tests are unaffected.

    cancel_event, when provided (Phase 10.5), is an asyncio.Event the TUI sets
    on Ctrl-C. It is checked at the top of each inner-loop pass; if set, it is
    cleared, an "agent_cancelled" event is emitted, and the inner loop breaks
    (cooperative, not preemptive — one in-flight streaming response may still
    complete before the cancel takes effect). When None (the default) the check
    is skipped, preserving backward compatibility.
    """
    system_prompt = build_system_prompt()
    messages: list[dict] = [{"role": "user", "content": task}]
    if pending_messages is None:
        pending_messages = []

    # OUTER LOOP: re-enters if follow-up messages arrive. Runs once for now.
    while True:
        has_more_tool_calls = True
        iteration = 0

        # INNER LOOP: the tool-call cycle.
        while has_more_tool_calls and iteration < MAX_ITERATIONS:
            # Cooperative cancel: Ctrl-C in the TUI sets this event.
            if cancel_event is not None and cancel_event.is_set():
                cancel_event.clear()
                emit({"type": "agent_cancelled"})
                break  # exit inner loop; outer loop waits for input

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

    # ── Command allowlist gate (bash only) ────────────────────────────────
    # Default-deny: only explicitly permitted programs may run via bash.
    # Sits at the beforeToolCall position — after the call is parsed, before
    # the tool function is dispatched. A denial returns is_error=True so the
    # model reads the reason and adapts rather than crashing.
    if name == "bash":
        verdict = check_command(args.get("command", ""))
        if not verdict.allowed:
            emit({"type": "tool_call_end", "index": tool_call.get("index", 0),
                  "tool_call_id": tool_call["id"], "name": name,
                  "content": f"Error: {verdict.reason}", "is_error": True, "chars": 0})
            return ToolResult(
                tool_call["id"], name, f"Error: {verdict.reason}", is_error=True
            )
    # ─────────────────────────────────────────────────────────────────────

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
