from __future__ import annotations

import asyncio
import json

from compaction import compact_if_needed
from config import MAX_ITERATIONS
from logging_config import logger
from policy import PolicyEngine
from prompts import build_system_prompt
from provider import stream_response
from renderer import emit
from tools import TOOL_REGISTRY
from types_ import ToolResult

_policy = PolicyEngine.from_env()  # reads AGENT_PERMISSION_MODE once at startup
_prompt_lock = asyncio.Lock()  # serialise stdin prompts in ask mode


async def _prompt_user(name: str, args: dict) -> bool:
    """Display a permission request and wait for the user's answer.

    Serialised with _prompt_lock so parallel tool calls don't interleave their
    input() prompts on the terminal.
    """
    async with _prompt_lock:
        print(f"\n[PERMISSION REQUEST] Tool: {name}")
        for key, value in args.items():
            text = str(value)
            preview = text[:200] + ("..." if len(text) > 200 else "")
            print(f"  {key}: {preview}")
        response = await asyncio.to_thread(input, "Allow? [y/N] ")
        return response.strip().lower() == "y"


async def run_agent(
    task: str,
    pending_messages: list[dict] | None = None,
    cancel_event: asyncio.Event | None = None,
    system_prompt: str | None = None,
    before_tool_call=None,
    after_tool_call=None,
    model: str | None = None,
    get_steering_messages=None,
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

    system_prompt, when provided (Phase 13.1), is the fully-built system prompt
    (e.g. carrying project instructions folded in via build_system_prompt's
    extra=...). When None (the default) it is built here with no extra, so
    existing callers and tests are unaffected.

    before_tool_call / after_tool_call, when provided (Phase 13.2), are async
    hook functions threaded into _execute_one_tool. before_tool_call(name, args)
    runs before dispatch; returning False denies the call (error ToolResult,
    tool never runs). after_tool_call(name, args, result) runs after a
    successful dispatch and its return value replaces the result string. Both
    default to None, leaving the loop unchanged for existing callers.

    model, when provided (Phase 13.6), overrides the configured MODEL for this
    run — it is threaded straight to stream_response so the agent loop itself is
    provider-agnostic. When None (the default) the configured MODEL is used.

    get_steering_messages, when provided (Phase 15), is an async callable taking
    no arguments and returning a list of message dicts. After the inner tool-call
    cycle finishes, the outer loop awaits it; any returned messages are appended
    to pending_messages, flushed into the conversation at the top of the next
    inner-loop pass, and the agent continues from where it left off (prior tool
    calls are NOT replayed). Returning an empty list ends the run. The loop does
    not know whether messages come from a stdin reader, an asyncio.Queue, an RPC
    signal, or a test fixture — it only sees a list. When None (the default) the
    outer loop runs exactly once, preserving backward compatibility.

    cancel_event, when provided (Phase 10.5), is an asyncio.Event the TUI sets
    on Ctrl-C. It is checked at the top of each inner-loop pass; if set, it is
    cleared, an "agent_cancelled" event is emitted, and the inner loop breaks
    (cooperative, not preemptive — one in-flight streaming response may still
    complete before the cancel takes effect). When None (the default) the check
    is skipped, preserving backward compatibility.
    """
    logger.info("agent starting: {!r}", task)
    if system_prompt is None:
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
            logger.debug("iteration {}/{}", iteration, MAX_ITERATIONS)

            # Flush any steering follow-ups before the next model call so a
            # message injected after a tool batch is seen by the model.
            if pending_messages:
                messages.extend(pending_messages)
                pending_messages.clear()

            # ── Phase A: stream the model response, accumulating as we go. ──
            # Compaction gate (Phase 16): compact_if_needed returns a context
            # that fits the window without ever mutating the source-of-truth
            # `messages` list. Below the threshold it returns `messages`
            # unchanged; above it, a new, shorter list. We send the compacted
            # view to the model but keep growing `messages` as the real history.
            context_to_send = await compact_if_needed(messages, system_prompt)

            text_buf = ""
            tool_acc: dict[int, dict] = {}
            finish_reason = None

            async for chunk in stream_response(
                messages=context_to_send,
                system_prompt=system_prompt,
                model=model,
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
                    slot = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments_buf": ""})
                    if tc_chunk.id:
                        slot["id"] = tc_chunk.id
                    fn = getattr(tc_chunk, "function", None)
                    if fn and fn.name:
                        slot["name"] = fn.name
                        emit(
                            {
                                "type": "tool_call_start",
                                "index": idx,
                                "tool_call_id": slot["id"],
                                "name": fn.name,
                            }
                        )
                    if fn and fn.arguments:
                        slot["arguments_buf"] += fn.arguments

            emit(
                {
                    "type": "turn_end",
                    "iteration": iteration,
                    "finish_reason": finish_reason or "stop",
                    "tool_calls_count": len(tool_acc),
                }
            )

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
            results = await _execute_tools_parallel(
                parsed_calls,
                before_tool_call=before_tool_call,
                after_tool_call=after_tool_call,
            )

            # ── Phase E: push one role:"tool" message per result. ──────────
            for r in results:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": r.tool_call_id,
                        "content": r.content,
                    }
                )

        # ── Steering poll (Phase 15) ──────────────────────────────────────
        # The inner loop has finished (the model stopped or the iteration cap
        # was hit). Ask the caller for follow-up messages. If any arrive, they
        # land in pending_messages, get flushed at the top of the next inner
        # pass, and the agent continues — prior tool calls are not replayed.
        # No callable, or an empty return, ends the run.
        if get_steering_messages is not None:
            new_messages = await get_steering_messages()
            if new_messages:
                pending_messages.extend(new_messages)
        if not pending_messages:
            break

    logger.info("agent finished after {} iteration(s)", iteration)
    emit({"type": "agent_end", "total_iterations": iteration, "status": "ok"})
    return messages


async def _execute_tools_parallel(
    tool_calls: list[dict],
    before_tool_call=None,
    after_tool_call=None,
) -> list[ToolResult]:
    """Run every requested tool concurrently and gather their results in order.

    Hooks (Phase 13.2) are threaded through to each _execute_one_tool. When both
    are None (the default) behaviour is identical to before.
    """
    return await asyncio.gather(
        *(
            _execute_one_tool(
                tc,
                before_tool_call=before_tool_call,
                after_tool_call=after_tool_call,
            )
            for tc in tool_calls
        )
    )


async def _execute_one_tool(
    tool_call: dict,
    before_tool_call=None,  # async (name, args) -> bool | None
    after_tool_call=None,  # async (name, args, result) -> str
) -> ToolResult:
    """Look up one tool by name, call it, and wrap the outcome in a ToolResult.

    Both an unknown tool and an exception become an is_error result rather than
    propagating — the loop keeps running and the model can read the error.
    """
    name = tool_call["name"]
    args = tool_call["input"]

    # ── Unknown-tool check (before the policy gate) ───────────────────────
    # An unknown tool can never be dispatched, so there is nothing to gate or
    # prompt for — short-circuit to the error so the model can correct itself.
    logger.debug("executing tool {} with {}", name, args)

    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        logger.warning("unknown tool requested: {}", name)
        emit(
            {
                "type": "tool_call_end",
                "index": tool_call.get("index", 0),
                "tool_call_id": tool_call["id"],
                "name": name,
                "content": f"Unknown tool: {name}",
                "is_error": True,
                "chars": 0,
            }
        )
        return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)

    # ── beforeToolCall hook (Phase 13.2) ──────────────────────────────────
    # Runs before the policy gate and dispatch. Returning False denies the
    # call — the tool never runs and the model reads the denial as an error.
    # Returning None or True (or no hook at all) lets the call proceed.
    if before_tool_call is not None:
        approved = await before_tool_call(name, args)
        if approved is False:
            reason = f"Tool call denied: {name}"
            emit(
                {
                    "type": "tool_call_end",
                    "index": tool_call.get("index", 0),
                    "tool_call_id": tool_call["id"],
                    "name": name,
                    "content": reason,
                    "is_error": True,
                    "chars": 0,
                }
            )
            return ToolResult(tool_call["id"], name, reason, is_error=True)

    # ── Policy gate ───────────────────────────────────────────────────────
    # The PolicyEngine (selected by AGENT_PERMISSION_MODE) evaluates the call
    # before dispatch. It subsumes the Layer 12.2 allowlist gate (now inside
    # CommandAllowlistRule) and adds read-only / ask / auto postures. A deny or
    # an unapproved ask returns is_error=True so the model reads the reason and
    # adapts rather than crashing.
    decision = _policy.check(name, args)

    if decision.outcome == "deny":
        reason = f"Error: tool call denied — {decision.reason}"
        emit(
            {
                "type": "tool_call_end",
                "index": tool_call.get("index", 0),
                "tool_call_id": tool_call["id"],
                "name": name,
                "content": reason,
                "is_error": True,
                "chars": 0,
            }
        )
        return ToolResult(tool_call["id"], name, reason, is_error=True)

    if decision.outcome == "ask":
        approved = await _prompt_user(name, args)
        if not approved:
            reason = f"Tool call '{name}' was not approved."
            emit(
                {
                    "type": "tool_call_end",
                    "index": tool_call.get("index", 0),
                    "tool_call_id": tool_call["id"],
                    "name": name,
                    "content": reason,
                    "is_error": True,
                    "chars": 0,
                }
            )
            return ToolResult(tool_call["id"], name, reason, is_error=True)
    # outcome == "allow" — fall through to dispatch
    # ─────────────────────────────────────────────────────────────────────

    # tool_call_start was already emitted during streaming; no event here.
    try:
        result = await fn(**args)
    except Exception as e:
        logger.exception("tool {} raised", name)
        emit(
            {
                "type": "tool_call_end",
                "index": tool_call.get("index", 0),
                "tool_call_id": tool_call["id"],
                "name": name,
                "content": f"Error: {e}",
                "is_error": True,
                "chars": 0,
            }
        )
        return ToolResult(tool_call["id"], name, f"Error: {e}", is_error=True)
    # ── afterToolCall hook (Phase 13.2) ───────────────────────────────────
    # Runs after a successful dispatch. Its return value replaces the result
    # string, so hook authors must return the result (even if unmodified) to
    # log, redact, or transform tool output before it enters message history.
    if after_tool_call is not None:
        result = await after_tool_call(name, args, result)

    logger.debug("tool {} ok: {} chars", name, len(result))
    emit(
        {
            "type": "tool_call_end",
            "index": tool_call.get("index", 0),
            "tool_call_id": tool_call["id"],
            "name": name,
            "content": result,
            "is_error": False,
            "chars": len(result),
        }
    )
    return ToolResult(tool_call["id"], name, result)
