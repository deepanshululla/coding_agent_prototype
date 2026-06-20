"""The pluggable-architecture seam.

An *architecture* is the agent's control-flow strategy — how it turns a task
into model calls and tool dispatches. The default (`reactive`, in agent.py) is
the single tool-call loop; alternates (orchestrator-worker, evaluator-optimizer,
planner-executor) compose the same primitives differently.

This module is the neutral seam: it knows nothing about agent.py (so there is no
import cycle). It defines the strategy Protocol, the per-run context object, and
a name → instance registry resolved the same way themes are (unknown name falls
back to the default with a warning).
"""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import asyncio

# The name the registry falls back to when an unknown architecture is requested.
# Registered by agent.py at import time.
DEFAULT_ARCHITECTURE = "reactive"


@dataclass
class RunContext:
    """Everything an architecture needs to run a task, in one object.

    These are the seams run_agent historically threaded as loose keyword
    arguments. Per-run state lives here so the architecture instances themselves
    stay stateless and shareable across runs.

    depth tracks sub-agent nesting (the orchestrator-worker architecture spawns
    child runs); it lets architectures cap recursion.
    """

    system_prompt: str
    pending_messages: list[dict] = field(default_factory=list)
    cancel_event: asyncio.Event | None = None
    before_tool_call: Callable[..., Awaitable] | None = None
    after_tool_call: Callable[..., Awaitable] | None = None
    model: str | None = None
    get_steering_messages: Callable[[], Awaitable[list[dict]]] | None = None
    depth: int = 0


@runtime_checkable
class AgentArchitecture(Protocol):
    """A swappable agent control-flow strategy.

    Implementations are stateless singletons: all per-run state arrives via the
    RunContext, so one instance serves every run. ``name`` is set by the
    ``register`` decorator from the registry key.
    """

    name: str

    async def run(self, task: str, ctx: RunContext) -> list[dict]:
        """Run ``task`` to completion and return the final message history."""
        ...


# name → ready-to-use architecture instance.
ARCHITECTURES: dict[str, AgentArchitecture] = {}


def register(name: str) -> Callable[[type], type]:
    """Class decorator: stamp ``name`` onto the class, instantiate it, and add
    the instance to the registry. Returns the class unchanged."""

    def deco(cls: type) -> type:
        cls.name = name  # type: ignore[attr-defined]
        ARCHITECTURES[name] = cls()
        return cls

    return deco


def get_architecture(name: str | None = None) -> AgentArchitecture:
    """Resolve an architecture by name, falling back to DEFAULT_ARCHITECTURE.

    ``None`` (no selection) resolves to the default silently; an explicit but
    unknown name warns on stderr before falling back, mirroring get_theme.
    """
    resolved = name or DEFAULT_ARCHITECTURE
    if resolved not in ARCHITECTURES:
        if resolved != DEFAULT_ARCHITECTURE:
            print(
                f"unknown architecture {resolved!r}, using {DEFAULT_ARCHITECTURE!r}",
                file=sys.stderr,
            )
        resolved = DEFAULT_ARCHITECTURE
    return ARCHITECTURES[resolved]
