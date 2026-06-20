from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolResult:
    """The outcome of executing one tool call.

    The agent loop turns each ToolResult into a role:"tool" message addressed
    to the originating tool_call_id. is_error lets the loop (and the model)
    distinguish a failed tool from a successful one without parsing content.
    """

    tool_call_id: str
    tool_name: str
    content: str
    is_error: bool = False
