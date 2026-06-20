"""Ready-to-use tool-call hook implementations (Phase 13.2).

Hooks are plain async functions passed to ``run_agent`` (and threaded down into
``_execute_one_tool``) — not a plugin registry. A ``before_tool_call`` hook has
signature ``async (name, args) -> bool | None``; returning ``False`` denies the
call. An ``after_tool_call`` hook has signature ``async (name, args, result) ->
str``; its return value replaces the result string (so it must return the
result, even when unmodified).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

# JSONL log path, relative to the cwd. Could be made configurable via an env
# var later; hardcoded here to keep the example self-contained.
LOG_PATH = Path(".agent-tool-log.jsonl")

# Read-only tools that never need a confirmation prompt.
ALWAYS_ALLOW = frozenset({"read_file", "list_dir", "grep", "find_files"})


async def log_after_tool_call(name: str, args: dict, result: str) -> str:
    """Log every tool call to a JSONL file; return the result unchanged."""
    entry = {
        "ts": datetime.now(UTC).isoformat(),
        "tool": name,
        "args": args,
        "result_len": len(result),
        "result_preview": result[:200],
    }
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return result  # pass through unchanged


async def confirm_before_tool_call(name: str, args: dict) -> bool:
    """Prompt the user before any write/execute tool. Read-only tools pass silently.

    Uses run_in_executor so the blocking input() call does not stall the event
    loop. Note that parallel tool calls dispatched via asyncio.gather fire this
    hook concurrently, so the user may see two prompts at once — serialise tool
    dispatch upstream if that matters for an interactive gate.
    """
    if name in ALWAYS_ALLOW:
        return True
    loop = asyncio.get_event_loop()
    formatted = ", ".join(f"{k}={v!r}" for k, v in args.items())
    answer = await loop.run_in_executor(None, input, f"\n  Allow {name}({formatted})? [y/N] ")
    return answer.strip().lower() == "y"
