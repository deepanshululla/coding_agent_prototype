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


@dataclass
class Memory:
    """A persistent memory entry stored as a markdown file with frontmatter.

    Memories are stored in ~/.agent_memory/<project_hash>/ and allow the agent
    to recall information across conversations (sessions).
    """

    name: str  # kebab-case slug
    description: str  # one-line summary
    type: str  # user | feedback | project | reference
    content: str  # markdown body
    created: str  # ISO timestamp
    updated: str  # ISO timestamp
