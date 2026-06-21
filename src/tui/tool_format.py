# src/tui/tool_format.py

"""Turn a tool call (name + input) into human-readable display strings.

Shared by the transcript pane (full ``●`` / ``└`` lines) and the activity panel
(compact label), so both name *which* file is read, *which* command runs, and
*which* file changed — not just the tool's type.

Handles both naming conventions seen in this project:
  * the `claude -p` fork's CamelCase tools — Read, Edit, Write, Bash, Grep, Glob
  * this project's own snake_case tools — read_file, edit_file, bash, find_files…
and the matching input-key differences (file_path vs path).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Max characters for the compact panel label / truncated detail.
_SHORT_LIMIT = 24


@dataclass
class ToolDisplay:
    """How one tool call should appear in the UI.

    summary    — the headline (``Reading file``, ``Edited x.py (+5 −3)``).
    detail     — the second line under the headline (path / command), or None
                 when the summary already carries everything.
    short      — a compact one-cell label for the narrow activity-panel column.
    expandable — whether there is more to show than the summary/detail (drives
                 the "(ctrl+o to expand)" hint; the toggle itself lands later).
    """

    summary: str
    detail: str | None
    short: str
    expandable: bool


def _truncate(text: str, limit: int = _SHORT_LIMIT) -> str:
    text = text.strip().replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _basename(path: str) -> str:
    return os.path.basename(path.rstrip("/")) or path


def _line_count(text: str) -> int:
    """Lines in a string: 0 for empty, else newline count + 1."""
    return text.count("\n") + 1 if text else 0


def _pick(tool_input: dict, *keys: str, default: str = "?") -> str:
    for key in keys:
        value = tool_input.get(key)
        if value:
            return str(value)
    return default


def format_tool_call(name: str, tool_input: dict | None) -> ToolDisplay:
    """Build the :class:`ToolDisplay` for a tool call.

    Recognizes the common file/command/search tools by name (either convention)
    and falls back to the raw tool name for anything unrecognized, so a new or
    custom tool still renders sensibly.
    """
    tool_input = tool_input or {}
    n = name.lower()

    if n in ("read", "read_file"):
        path = _pick(tool_input, "file_path", "path")
        return ToolDisplay("Reading file", path, _basename(path), expandable=True)

    if n in ("edit", "edit_file", "multiedit", "multi_edit"):
        path = _pick(tool_input, "file_path", "path")
        adds = _line_count(str(tool_input.get("new_string", "")))
        dels = _line_count(str(tool_input.get("old_string", "")))
        summary = f"Edited {path} (+{adds} −{dels})"
        return ToolDisplay(summary, None, _basename(path), expandable=True)

    if n in ("write", "write_file"):
        path = _pick(tool_input, "file_path", "path")
        adds = _line_count(str(tool_input.get("content", "")))
        return ToolDisplay(f"Wrote {path} (+{adds})", None, _basename(path), expandable=True)

    if n in ("bash", "shell", "run_bash"):
        cmd = _pick(tool_input, "command")
        return ToolDisplay("Running command", cmd, _truncate(cmd), expandable=False)

    if n in ("grep", "search"):
        pat = _pick(tool_input, "pattern", "query")
        return ToolDisplay("Searching", pat, _truncate(pat), expandable=False)

    if n in ("glob", "find_files"):
        pat = _pick(tool_input, "pattern", "glob")
        return ToolDisplay("Finding files", pat, _truncate(pat), expandable=False)

    if n in ("list_dir", "ls"):
        path = _pick(tool_input, "path", default=".")
        return ToolDisplay("Listing directory", path, _basename(path), expandable=False)

    # Unknown tool: show its name, with the input compacted onto the detail line.
    detail = ", ".join(f"{k}={_truncate(str(v), 16)}" for k, v in tool_input.items()) or None
    return ToolDisplay(name, detail, _truncate(name), expandable=False)
