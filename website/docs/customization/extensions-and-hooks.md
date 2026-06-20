---
sidebar_position: 2
title: Extensions & Hooks
description: How pi's beforeToolCall/afterToolCall and transformContext hooks work, and where you'd add equivalent hook points in this project's agent loop.
---

# Extensions & Hooks

Pi.dev's agent loop is designed around named hook points — `beforeToolCall`, `afterToolCall`, and `transformContext` — that let you intercept execution without forking the core loop. This project does not implement hooks in v1, but the loop is structured so they can be added in exactly the places pi puts them.

This page explains what hooks do in pi, where the equivalent spots are in `src/agent.py`, and what you'd build if you needed them.

:::note
Hooks are a planned extension point. The PLAN.md `"What To Skip in v1"` section explicitly defers `beforeToolCall`/`afterToolCall` hooks ("Add if you want permission prompts"). The description below reflects the intended design, not shipped code.
:::

## What hooks do in pi

Pi exposes three hook slots on the agent:

| Hook | When it fires | Typical uses |
|------|---------------|--------------|
| `beforeToolCall(tool, args)` | After the model requests a tool, before execution | Permission prompts, argument validation, dry-run mode, logging |
| `afterToolCall(tool, args, result)` | After the tool returns, before the result is pushed to history | Output redaction, result transformation, audit logging |
| `transformContext(messages)` | When the context window gets large | Compaction — summarize old turns to stay under the token limit |

All three are optional. If you don't register a hook, the loop behaves as if the hook returned its input unchanged.

## Where to add hook points in `_execute_one_tool`

In `src/agent.py`, every tool call goes through `_execute_one_tool`. This is the natural home for `beforeToolCall` and `afterToolCall`:

```python
async def _execute_one_tool(tool_call: dict) -> ToolResult:
    name = tool_call["name"]
    args = tool_call["input"]

    # ── beforeToolCall ─────────────────────────────────────────────
    # (hook point — not yet implemented)
    # approved = await before_tool_call_hook(name, args)
    # if not approved:
    #     return ToolResult(tool_call["id"], name, "Tool call denied", is_error=True)

    print(f"  [executing {name} {args}]")
    try:
        fn = TOOL_REGISTRY.get(name)
        if fn is None:
            return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
        result = await fn(**args)
        print(f"  [✓ {name}: {len(result)} chars]")

        # ── afterToolCall ───────────────────────────────────────────
        # (hook point — not yet implemented)
        # result = await after_tool_call_hook(name, args, result)

        return ToolResult(tool_call["id"], name, result)
    except Exception as e:
        return ToolResult(tool_call["id"], name, str(e), is_error=True)
```

Because `_execute_tools_parallel` calls `_execute_one_tool` via `asyncio.gather`, both hooks run concurrently across all tool calls in a batch — which is what you want for logging but requires care for interactive permission prompts (you'd need to serialize those, or gather confirmations up front before dispatching).

## Implementing a `beforeToolCall` permission prompt

The simplest useful hook is an interactive permission prompt — show the user what the agent is about to do and let them approve or deny:

```python
import asyncio

ALWAYS_ALLOW = {"read_file", "list_dir", "grep", "find_files"}
ALWAYS_DENY: set[str] = set()

async def before_tool_call_hook(name: str, args: dict) -> bool:
    """Return True to allow, False to deny."""
    if name in ALWAYS_ALLOW:
        return True
    if name in ALWAYS_DENY:
        print(f"  [denied: {name}]")
        return False

    # Interactive prompt (blocks; for use in non-parallel mode)
    formatted_args = ", ".join(f"{k}={v!r}" for k, v in args.items())
    response = input(f"\n  Allow {name}({formatted_args})? [y/N] ")
    return response.strip().lower() == "y"
```

:::warning
`input()` blocks the event loop. If you run this inside `asyncio.gather` with other concurrent tool calls, those calls will stall until the user responds. For parallel execution, collect all tool calls first, prompt for all of them, then dispatch the approved subset.
:::

A cleaner async-safe approach:

```python
async def _ask_permission(name: str, args: dict) -> bool:
    loop = asyncio.get_event_loop()
    formatted = ", ".join(f"{k}={v!r}" for k, v in args.items())
    answer = await loop.run_in_executor(
        None, input, f"\n  Allow {name}({formatted})? [y/N] "
    )
    return answer.strip().lower() == "y"
```

See [Permissions](../operations/permissions.md) for a fuller discussion of permission models.

## Implementing an `afterToolCall` logging hook

A logging hook is purely additive — it receives the result and can transform it or just record it:

```python
import json
from datetime import datetime
from pathlib import Path

LOG_PATH = Path(".agent-tool-log.jsonl")

async def after_tool_call_hook(name: str, args: dict, result: str) -> str:
    entry = {
        "ts": datetime.utcnow().isoformat(),
        "tool": name,
        "args": args,
        "result_len": len(result),
        "result_preview": result[:200],
    }
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return result  # pass through unchanged
```

### Output redaction

If tool output might contain secrets (API keys, tokens, credentials), the `afterToolCall` hook is the right place to scrub them before they enter message history:

```python
import re

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{32,}"),          # OpenAI / Anthropic keys
    re.compile(r"(?i)(password|token|secret)\s*=\s*\S+"),
]

async def after_tool_call_hook(name: str, args: dict, result: str) -> str:
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result
```

:::tip
Redact in the hook, not in the tool. The tool should return what it found — the hook decides what reaches the model's context.
:::

## The `transformContext` hook — compaction

Pi's `transformContext` hook fires when the accumulated message history grows large. It receives the full message list and returns a shorter version — typically by summarizing early turns into a single message.

In this project, the equivalent is a function you'd call at the top of the inner loop, before `stream_response`:

```python
MAX_CONTEXT_CHARS = 150_000  # rough threshold

async def transform_context(messages: list[dict]) -> list[dict]:
    total = sum(len(str(m.get("content", ""))) for m in messages)
    if total < MAX_CONTEXT_CHARS:
        return messages
    # Summarize everything except the last few turns
    # (implementation depends on your compaction strategy)
    return messages  # placeholder

# In the inner loop:
messages = await transform_context(messages)
async for chunk in stream_response(messages, system_prompt):
    ...
```

See [Compaction](../advanced/compaction.md) for the full compaction strategy.

## Wiring hooks into the loop

If you add all three hooks, the call sites in `src/agent.py` look like this:

```python
# At the top of the inner loop body:
messages = await transform_context_hook(messages)          # transformContext

# Inside _execute_one_tool:
approved = await before_tool_call_hook(name, args)        # beforeToolCall
if not approved:
    return ToolResult(tool_call["id"], name, "Denied", is_error=True)
# ... execute tool ...
result = await after_tool_call_hook(name, args, result)   # afterToolCall
```

Keep hooks as plain async functions. Pass them into `run_agent` as optional keyword arguments so they're easy to swap in tests:

```python
async def run_agent(
    task: str,
    before_tool_call=None,
    after_tool_call=None,
    transform_context=None,
) -> None:
    ...
```

## Related pages

- [Permissions](../operations/permissions.md) — permission models and approval flows
- [Compaction](../advanced/compaction.md) — context window management via `transformContext`
- [The Agent Loop](../architecture/the-agent-loop.md) — where hooks slot into the inner loop
