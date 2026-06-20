"""Phase 14.1 — The SDK.

A thin library entry point that lets callers drive the agent in-process and
receive every typed event as a list, alongside the final message history, so
they never have to parse stdout.

The mechanism is intentionally minimal: `run_agent_collecting` temporarily
replaces the `emit` seam for the duration of a single `run_agent` call with a
wrapper that appends each event to a list and forwards to the original emitter,
then restores the original in `finally`. Because `agent.py` does
`from renderer import emit`, the live reference the loop calls is `agent.emit`;
we patch that (and `renderer.emit` too, so any code that re-reads the seam sees
the same wrapper). Restoring in `finally` means an exception inside the loop
never leaves the renderer in a broken state.

Limitation: the patch mutates module-level names, so two concurrent in-process
calls to `run_agent_collecting` would race on the replacement. This is fine for
a single-threaded async event loop driving one agent at a time; a production
SDK would inject a callback directly into `run_agent` (deferred to Phase 15,
where steering makes a first-class callback necessary).
"""

from __future__ import annotations

import agent as _agent
import renderer as _renderer


async def run_agent_collecting(task: str, **kwargs) -> tuple[list[dict], list[dict]]:
    """Run the agent on `task`, collecting every emitted event.

    Returns ``(events, messages)`` where ``events`` is the ordered list of typed
    event dicts the agent emitted (text_delta, tool_call_start, tool_call_end,
    turn_end, agent_end, ...) and ``messages`` is the final message history that
    a direct ``run_agent(task)`` call would return.

    Extra keyword arguments are forwarded to ``run_agent`` unchanged (e.g.
    ``system_prompt=``, ``model=``, ``before_tool_call=``).
    """
    collected: list[dict] = []

    original_emit = _renderer.emit

    def collecting_emit(event: dict) -> None:
        collected.append(event)
        original_emit(event)

    _renderer.emit = collecting_emit
    _agent.emit = collecting_emit
    try:
        messages = await _agent.run_agent(task, **kwargs)
    finally:
        _renderer.emit = original_emit
        _agent.emit = original_emit

    return collected, messages
