"""Policy engine: a composable gate that answers 'can this tool call run?'
before _execute_one_tool dispatches to the tool function.

Usage:
    _policy = PolicyEngine.from_env()   # call once at module level

    decision = _policy.check(name, args)
    if decision.outcome == "deny":
        return ToolResult(..., is_error=True)
    if decision.outcome == "ask":
        approved = await _prompt_user(name, args)
        if not approved:
            return ToolResult(..., is_error=True)
    # outcome == "allow" — dispatch
"""

from __future__ import annotations

import os
import pathlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal


# ── Decision ─────────────────────────────────────────────────────────────────

@dataclass
class Decision:
    outcome: Literal["allow", "deny", "ask"]
    reason: str = ""


# ── Rules ────────────────────────────────────────────────────────────────────

class Rule(ABC):
    @abstractmethod
    def evaluate(self, tool_name: str, args: dict) -> Decision | None:
        """Return a Decision to short-circuit, or None to pass to the next rule."""
        ...


class ReadToolRule(Rule):
    """Auto-allow read-only tools so they never prompt or get denied.

    Read tools (read_file, grep, find_files, list_dir) are safe in every mode —
    read-only, ask, and auto all let them run freely (see the tool-behavior
    table in the Permission Modes design doc). Placed at the front of each rule
    set so reads short-circuit before any default outcome applies.
    """
    READ_TOOLS = {"read_file", "grep", "find_files", "list_dir"}

    def evaluate(self, tool_name: str, args: dict) -> Decision | None:
        if tool_name in self.READ_TOOLS:
            return Decision("allow")
        return None


class ReadOnlyRule(Rule):
    """Deny all write and execute tools unconditionally."""
    WRITE_EXECUTE = {"bash", "write_file", "edit_file"}

    def evaluate(self, tool_name: str, args: dict) -> Decision | None:
        if tool_name in self.WRITE_EXECUTE:
            return Decision(
                "deny",
                f"'{tool_name}' is a write/execute tool; read-only mode is active",
            )
        return None


class CommandAllowlistRule(Rule):
    """Apply the command allowlist to bash calls (Layer 12.2)."""

    def evaluate(self, tool_name: str, args: dict) -> Decision | None:
        if tool_name != "bash":
            return None
        from allowlist import check_command
        verdict = check_command(args.get("command", ""))
        if not verdict.allowed:
            return Decision("deny", verdict.reason)
        return Decision("allow")   # allowlisted — no need to ask


class PathRestrictionRule(Rule):
    """Deny file writes outside the allowed root (default: cwd)."""

    def __init__(self, allowed_root: str | None = None):
        self.root = pathlib.Path(allowed_root or os.getcwd()).resolve()

    def evaluate(self, tool_name: str, args: dict) -> Decision | None:
        if tool_name not in {"write_file", "edit_file"}:
            return None
        try:
            resolved = pathlib.Path(args.get("path", "")).resolve()
            if not resolved.is_relative_to(self.root):
                return Decision(
                    "deny",
                    f"path {resolved} is outside allowed root {self.root}",
                )
        except ValueError:
            return Decision("deny", "could not resolve path")
        return None   # path is safe; let other rules decide


# ── Engine ───────────────────────────────────────────────────────────────────

class PolicyEngine:
    """Evaluate a tool call against an ordered list of rules.

    The first rule that returns a non-None Decision wins.
    If no rule matches, the engine's default outcome applies.
    """

    def __init__(
        self,
        rules: list[Rule],
        default: Literal["allow", "deny", "ask"] = "ask",
    ):
        self.rules = rules
        self.default = default

    @classmethod
    def from_env(cls) -> PolicyEngine:
        """Build an engine from AGENT_PERMISSION_MODE (default: 'ask')."""
        mode = os.environ.get("AGENT_PERMISSION_MODE", "ask")

        if mode == "read-only":
            return cls(
                rules=[
                    ReadToolRule(),    # reads run freely
                    ReadOnlyRule(),    # writes/execs denied
                ],
                default="deny",
            )

        if mode == "auto":
            return cls(
                rules=[
                    ReadToolRule(),           # reads run freely
                    CommandAllowlistRule(),
                    PathRestrictionRule(),
                ],
                default="deny",   # auto still denies unknown/unlisted calls
            )

        # mode == "ask" (default)
        return cls(
            rules=[
                ReadToolRule(),           # reads run freely
                CommandAllowlistRule(),   # allowlisted bash calls run without prompting
                PathRestrictionRule(),    # out-of-root writes are denied without prompting
            ],
            default="ask",   # everything else goes to the user
        )

    def check(self, tool_name: str, args: dict) -> Decision:
        for rule in self.rules:
            decision = rule.evaluate(tool_name, args)
            if decision is not None:
                return decision
        return Decision(outcome=self.default, reason="no matching rule; default applied")
