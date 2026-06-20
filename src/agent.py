from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from architecture import RunContext, get_architecture, register
from compaction import compact_if_needed
from config import ARCHITECTURE, MAX_ITERATIONS
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


# ── Loop primitives ───────────────────────────────────────────────────────────
# stream_turn and execute_tools are the two reusable building blocks every
# architecture composes (see architecture.py). They live here — not in an
# architecture module — so they resolve `stream_response` and `emit` from this
# module's globals at call time, which is what lets the test suite monkeypatch
# `agent.stream_response` / `agent.emit` and have every architecture observe it.


@dataclass
class TurnResult:
    """The outcome of streaming one model turn.

    assistant_message is the assembled role:"assistant" message (with any
    tool_calls attached) ready to append to history. tool_calls is the *parsed*
    form for dispatch ({id, index, name, input}); it is empty when the model
    produced a plain-text turn (the stop signal).
    """

    assistant_message: dict
    tool_calls: list[dict]
    finish_reason: str
    text: str


async def stream_turn(
    messages: list[dict],
    *,
    system_prompt: str,
    model: str | None = None,
    iteration: int = 0,
) -> TurnResult:
    """Stream one model turn, emitting deltas as it goes, and return a TurnResult.

    Does not mutate ``messages``: the caller appends the assistant message (and
    any tool results) to history, so an architecture can inspect or discard a
    turn before committing it. Compaction (Phase 16) sends a compacted *view* to
    the model without ever touching the caller's real history.
    """
    context_to_send = await compact_if_needed(messages, system_prompt)

    text_buf = ""
    thinking_buf = ""
    thinking_signature = None
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

        # Extended thinking (Phase 17): reasoning streams on delta.thinking
        # before the answer; accumulate it and surface only on the debug channel.
        if getattr(delta, "thinking", None):
            thinking_buf += delta.thinking
            emit({"type": "thinking_delta", "delta": delta.thinking})
        # The signature verifies the thinking block on replay; capture the last.
        if getattr(delta, "signature", None):
            thinking_signature = delta.signature

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

    # Raw OpenAI-shaped tool_calls ride on the assistant message (arguments stay
    # a JSON string in history). Must be present even with empty content or the
    # provider rejects the next request as malformed.
    raw_tool_calls: list[dict[str, Any]] = [
        {
            "id": tc["id"],
            "type": "function",
            "function": {"name": tc["name"], "arguments": tc["arguments_buf"]},
        }
        for tc in tool_acc.values()
    ]

    # Extended thinking (Phase 17): a thinking block must be preserved verbatim
    # with its signature and placed BEFORE the text block. When no thinking
    # occurred, content stays a plain string, keeping the message shape
    # backward-compatible for every prior phase.
    if thinking_buf:
        thinking_block: dict = {"type": "thinking", "thinking": thinking_buf}
        if thinking_signature is not None:
            thinking_block["signature"] = thinking_signature
        content: object = [thinking_block, {"type": "text", "text": text_buf}]
    else:
        content = text_buf or None
    assistant_message: dict = {"role": "assistant", "content": content}
    if raw_tool_calls:
        assistant_message["tool_calls"] = raw_tool_calls

    # Parsed form for dispatch (what _execute_one_tool consumes).
    parsed_calls = [
        {
            "id": tc["id"],
            "index": i,
            "name": tc["function"]["name"],
            "input": json.loads(tc["function"]["arguments"] or "{}"),
        }
        for i, tc in enumerate(raw_tool_calls)
    ]

    return TurnResult(
        assistant_message=assistant_message,
        tool_calls=parsed_calls,
        finish_reason=finish_reason or "stop",
        text=text_buf,
    )


async def run_agent(
    task: str,
    pending_messages: list[dict] | None = None,
    cancel_event: asyncio.Event | None = None,
    system_prompt: str | None = None,
    before_tool_call=None,
    after_tool_call=None,
    model: str | None = None,
    get_steering_messages=None,
    architecture: str | None = None,
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

    architecture, when provided, selects the control-flow strategy by name (see
    architecture.py): "reactive" (the default single tool-call loop below),
    "orchestrator-worker", "evaluator-optimizer", or "planner-executor". An
    unknown name falls back to "reactive" with a warning. When None (the
    default) the configured AGENT_ARCHITECTURE is used, itself defaulting to
    "reactive" — so every existing caller is unaffected.
    """
    if system_prompt is None:
        system_prompt = build_system_prompt()
    ctx = RunContext(
        system_prompt=system_prompt,
        # Pass the caller's list through by reference (the TUI appends to it for
        # steering); only synthesize a fresh one when none was provided.
        pending_messages=pending_messages if pending_messages is not None else [],
        cancel_event=cancel_event,
        before_tool_call=before_tool_call,
        after_tool_call=after_tool_call,
        model=model,
        get_steering_messages=get_steering_messages,
    )
    _load_architectures()  # ensure the built-in alternates are registered
    # Explicit arg wins; otherwise the AGENT_ARCHITECTURE env default (reactive).
    return await get_architecture(architecture or ARCHITECTURE).run(task, ctx)


def _load_architectures() -> None:
    """Import the architectures package so its alternates self-register.

    Done lazily (not at module top) because those modules import this one; a
    top-level import would be circular. The reactive default is registered in
    this module, so resolution works even if the package import is a no-op.
    """
    try:
        import architectures  # noqa: F401  # ty: ignore[unresolved-import]
    except ModuleNotFoundError:
        pass  # only the built-in reactive architecture is available


@register("reactive")
class ReactiveAgent:
    """The default architecture: one streaming tool-call loop with steering.

    This is the loop the agent has always run, now expressed as a strategy over
    the stream_turn / execute_tools primitives. The OUTER loop re-enters when
    steering follow-ups arrive; the INNER loop is the tool-call cycle.
    """

    async def run(self, task: str, ctx: RunContext) -> list[dict]:
        logger.info("agent starting: {!r}", task)
        # An empty task (e.g. the TUI launched idle) seeds no user turn — the
        # agent waits for the first steering message instead of calling on "".
        messages: list[dict] = [{"role": "user", "content": task}] if task.strip() else []

        # OUTER LOOP: re-enters if follow-up messages arrive.
        while True:
            has_more_tool_calls = True
            iteration = 0

            # INNER LOOP: the tool-call cycle.
            while has_more_tool_calls and iteration < MAX_ITERATIONS:
                # Cooperative cancel: Ctrl-C in the TUI sets this event.
                if ctx.cancel_event is not None and ctx.cancel_event.is_set():
                    ctx.cancel_event.clear()
                    emit({"type": "agent_cancelled"})
                    break  # exit inner loop; outer loop waits for input

                # Flush any steering follow-ups before the next model call so a
                # message injected after a tool batch is seen by the model.
                if ctx.pending_messages:
                    messages.extend(ctx.pending_messages)
                    ctx.pending_messages.clear()

                # Nothing to send yet (empty initial task, no steering yet):
                # break to the steering poll and wait for the first message
                # instead of calling the model with an empty conversation.
                if not messages:
                    break

                iteration += 1
                logger.debug("iteration {}/{}", iteration, MAX_ITERATIONS)

                # ── Phase A+B: stream one turn, commit the assistant message. ─
                turn = await stream_turn(
                    messages,
                    system_prompt=ctx.system_prompt,
                    model=ctx.model,
                    iteration=iteration,
                )
                messages.append(turn.assistant_message)

                # ── Phase C: stop check — no tools means we are done. ────────
                if not turn.tool_calls:
                    has_more_tool_calls = False
                    continue

                # ── Phase D: dispatch the requested tools in parallel. ───────
                results = await execute_tools(
                    turn.tool_calls,
                    before_tool_call=ctx.before_tool_call,
                    after_tool_call=ctx.after_tool_call,
                )

                # ── Phase E: push one role:"tool" message per result. ────────
                for r in results:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": r.tool_call_id,
                            "content": r.content,
                        }
                    )

            # ── Steering poll (Phase 15) ──────────────────────────────────
            # The inner loop has finished (the model stopped or the iteration
            # cap was hit). Ask the caller for follow-up messages; any that
            # arrive are flushed at the top of the next inner pass and the agent
            # continues. No callable, or an empty return, ends the run.
            if ctx.get_steering_messages is not None:
                new_messages = await ctx.get_steering_messages()
                if new_messages:
                    ctx.pending_messages.extend(new_messages)
            if not ctx.pending_messages:
                break

        logger.info("agent finished after {} iteration(s)", iteration)
        emit({"type": "agent_end", "total_iterations": iteration, "status": "ok"})
        return messages


async def execute_tools(
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
