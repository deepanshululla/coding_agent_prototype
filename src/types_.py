"""Data structures that flow through the agent.

Named ``types_`` (trailing underscore) to avoid shadowing the stdlib ``types`` module.
These mirror pi's message types, kept deliberately minimal for v1: plain dicts are used
on the wire (the providers accept them directly), and these dataclasses are the typed
handles the agent loop and tools pass around internally.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolCall:
    """A single tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """The outcome of executing one tool call.

    ``is_error`` is True when the tool failed. Crucially, tools never raise — they return
    a descriptive ``content`` string and set this flag, so the model can read what went
    wrong and try another approach.
    """

    tool_call_id: str
    tool_name: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    """A conversation message.

    ``role`` is one of ``"user"``, ``"assistant"``, or ``"tool"``. ``content`` is a plain
    string for user/tool messages and may be ``None`` for an assistant turn that only
    carries tool calls.
    """

    role: str
    content: str | list | None
