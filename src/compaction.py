"""Phase 16 — Context Compaction.

Keep the agent from crashing on context-window overflow. ``compact_if_needed``
runs in the inner loop just before every ``stream_response`` call and returns a
(possibly shorter) message list *without mutating* the caller's source-of-truth
``messages``. The invariant: it returns either ``messages`` itself (passthrough)
or a brand-new shorter list — it never edits the input in place.

A threshold ladder picks the strategy from the estimated token count:

    estimate <  PASSTHROUGH_THRESHOLD          → passthrough (return unchanged)
    PASSTHROUGH ≤ estimate < DROP_THRESHOLD     → drop stale tool results
    DROP ≤ estimate < SUMMARISE_THRESHOLD       → summarise old turns via LLM
    estimate ≥ SUMMARISE_THRESHOLD              → keep recent turns only

Token estimation is a dependency-free heuristic: ``len(json.dumps(messages)) //
4`` (≈ 4 chars/token). ``litellm.token_counter`` is a more accurate but slower
alternative; the heuristic is fast and good enough to decide *whether* to
compact.

The thresholds are module-level constants read from the environment so they can
be lowered in tests (or production) without code changes:

    COMPACT_PASSTHROUGH_THRESHOLD   (default 100_000)
    COMPACT_DROP_THRESHOLD          (default 160_000)
    COMPACT_SUMMARISE_THRESHOLD     (default 190_000)
    COMPACT_KEEP_RECENT_TOOL_RESULTS (default 6)   how many newest tool results to keep
    COMPACT_KEEP_RECENT_MESSAGES    (default 10)    keep-recent-only window size

Every compaction emits a typed ``compaction`` event via ``emit`` so the event
stream and TUI can surface it.
"""

from __future__ import annotations

import json
import os

from logging_config import logger
from provider import stream_response
from renderer import emit


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# ── Threshold ladder (estimated tokens) ──────────────────────────────────────
PASSTHROUGH_THRESHOLD = _int_env("COMPACT_PASSTHROUGH_THRESHOLD", 100_000)
DROP_THRESHOLD = _int_env("COMPACT_DROP_THRESHOLD", 160_000)
SUMMARISE_THRESHOLD = _int_env("COMPACT_SUMMARISE_THRESHOLD", 190_000)

# How many of the newest tool results to keep when dropping stale ones.
KEEP_RECENT_TOOL_RESULTS = _int_env("COMPACT_KEEP_RECENT_TOOL_RESULTS", 6)
# Window size for the keep-recent-only (most aggressive) strategy.
KEEP_RECENT_MESSAGES = _int_env("COMPACT_KEEP_RECENT_MESSAGES", 10)


def estimate_tokens(messages: list[dict]) -> int:
    """Estimate the token cost of a message list.

    Heuristic: serialise to JSON and divide the character count by 4. This is
    dependency-free and fast; it only needs to be good enough to choose a
    compaction strategy, not to bill tokens.
    """
    return len(json.dumps(messages, default=str)) // 4


def _is_tool_result(msg: dict) -> bool:
    return msg.get("role") == "tool"


def _first_user_turn(messages: list[dict]) -> list[dict]:
    """Return the leading user turn(s) so the original task is never dropped.

    The keep-recent / summarise strategies anchor on the first user message so
    the agent never loses the task it was asked to do.
    """
    head: list[dict] = []
    for msg in messages:
        if msg.get("role") == "user":
            head.append(msg)
            break
        head.append(msg)
    return head


def _drop_stale_tool_results(messages: list[dict]) -> list[dict]:
    """Keep every non-tool message plus the newest KEEP_RECENT_TOOL_RESULTS.

    Stale tool outputs (old file reads, command output) are the cheapest thing
    to shed: they are bulky and rarely needed once the model has acted on them.
    Assistant turns (which carry the tool_calls structure) are always kept so
    the conversation stays well-formed. A dropped tool result is replaced with a
    short placeholder so the assistant's tool_call still has a matching reply —
    providers reject a tool_call with no corresponding tool message.
    """
    tool_indices = [i for i, m in enumerate(messages) if _is_tool_result(m)]
    keep_ids = set(tool_indices[-KEEP_RECENT_TOOL_RESULTS:]) if KEEP_RECENT_TOOL_RESULTS else set()

    out: list[dict] = []
    for i, msg in enumerate(messages):
        if _is_tool_result(msg) and i not in keep_ids:
            placeholder = dict(msg)
            placeholder["content"] = "[older tool output elided to save context]"
            out.append(placeholder)
        else:
            out.append(msg)
    return out


def _keep_recent_only(messages: list[dict]) -> list[dict]:
    """Most aggressive: keep the first user turn + the last KEEP_RECENT_MESSAGES.

    Used when even summarising would not fit. The first user turn is preserved so
    the agent never forgets the original task; the recent tail keeps it coherent
    on what it is doing right now. Care is taken not to start the tail on an
    orphaned tool message (a role:"tool" with no preceding assistant tool_call),
    which providers reject.
    """
    head = _first_user_turn(messages)
    head_len = len(head)

    tail = messages[max(head_len, len(messages) - KEEP_RECENT_MESSAGES):]
    # Drop any leading orphan tool messages from the tail.
    while tail and _is_tool_result(tail[0]):
        tail = tail[1:]
    return head + tail


async def _summarise_old_turns(messages: list[dict], system_prompt: str) -> list[dict]:
    """Summarise everything but the recent tail into one user message via the LLM.

    Splits history into a head to summarise and a recent tail to keep verbatim.
    A single non-streaming-style pass over ``stream_response`` produces a prose
    summary; the result is the first user turn, then a synthetic user message
    carrying the summary, then the verbatim tail. If the summary call fails for
    any reason we fall back to keep-recent-only rather than crash the agent.
    """
    head = _first_user_turn(messages)
    head_len = len(head)
    tail = messages[max(head_len, len(messages) - KEEP_RECENT_MESSAGES):]
    while tail and _is_tool_result(tail[0]):
        tail = tail[1:]

    to_summarise = messages[head_len:len(messages) - len(tail)]
    if not to_summarise:
        return _keep_recent_only(messages)

    summary_request = [
        {
            "role": "user",
            "content": (
                "Summarise the following conversation history into a concise set "
                "of bullet points capturing every decision, file touched, and fact "
                "the assistant will need to continue the task. Preserve identifiers, "
                "paths, and values verbatim.\n\n"
                + json.dumps(to_summarise, default=str)
            ),
        }
    ]

    try:
        summary_text = ""
        async for chunk in stream_response(
            messages=summary_request,
            system_prompt="You are a precise conversation summariser.",
        ):
            delta = chunk.choices[0].delta
            if getattr(delta, "content", None):
                summary_text += delta.content
        if not summary_text.strip():
            raise ValueError("empty summary")
    except Exception as exc:  # noqa: BLE001 — degrade gracefully, never crash the loop
        logger.warning("summarise compaction failed ({}); falling back to keep-recent", exc)
        return _keep_recent_only(messages)

    summary_msg = {
        "role": "user",
        "content": "[summary of earlier conversation]\n" + summary_text.strip(),
    }
    return head + [summary_msg] + tail


async def compact_if_needed(messages: list[dict], system_prompt: str) -> list[dict]:
    """Return a context list small enough to send, compacting only when needed.

    The source-of-truth ``messages`` is NEVER mutated: this returns either the
    same list object (passthrough) or a new, shorter list. The strategy is chosen
    by the threshold ladder on the estimated token count. Each compaction emits a
    ``compaction`` event so the UI can surface it.
    """
    estimate = estimate_tokens(messages)

    if estimate < PASSTHROUGH_THRESHOLD:
        return messages  # passthrough — same object, no allocation

    if estimate < DROP_THRESHOLD:
        strategy = "drop_stale_tool_results"
        compacted = _drop_stale_tool_results(messages)
    elif estimate < SUMMARISE_THRESHOLD:
        strategy = "summarise_old_turns"
        compacted = await _summarise_old_turns(messages, system_prompt)
    else:
        strategy = "keep_recent_only"
        compacted = _keep_recent_only(messages)

    after = estimate_tokens(compacted)
    logger.info(
        "compaction: strategy={} {} -> {} messages, ~{} -> ~{} tokens",
        strategy,
        len(messages),
        len(compacted),
        estimate,
        after,
    )
    emit(
        {
            "type": "compaction",
            "strategy": strategy,
            "messages_before": len(messages),
            "messages_after": len(compacted),
            "tokens_before": estimate,
            "tokens_after": after,
        }
    )
    return compacted
