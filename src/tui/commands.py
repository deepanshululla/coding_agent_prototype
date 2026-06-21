# src/tui/commands.py

"""Slash-command macros for the TUI input box.

Text typed into the input box that begins with "/" is a *command*, not a
steering message: it runs locally against the app and its output is echoed in
the transcript instead of being sent to the agent. This keeps quick operator
actions (inspect the model, check usage, switch models) out of the model's
context entirely.

The public entry point is ``dispatch(app, text)``:
  - returns None when ``text`` is not a command (caller steers as usual);
  - otherwise runs the command and returns the text to echo in the transcript.

Adding a command is one ``@command`` registration — keep handlers small and
have them return a plain string. They never raise: a bad command reports an
error string rather than crashing the input handler.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tui.app import AgentApp


@dataclass(frozen=True)
class _Command:
    name: str
    help: str
    run: Callable[[AgentApp, str], str]


_COMMANDS: dict[str, _Command] = {}


def command(name: str, help: str) -> Callable[[Callable], Callable]:
    """Register a slash-command handler under ``name`` with one-line ``help``."""

    def deco(fn: Callable[[AgentApp, str], str]) -> Callable[[AgentApp, str], str]:
        _COMMANDS[name] = _Command(name=name, help=help, run=fn)
        return fn

    return deco


def get_command_names() -> list[str]:
    """Return sorted list of all registered command names."""
    return sorted(_COMMANDS.keys())


def dispatch(app: AgentApp, text: str) -> str | None:
    """Run ``text`` as a slash command, or return None if it isn't one.

    Not a command (no leading "/") → None, so the caller steers as usual.
    A bare "/" or an unknown name → an error string (never raises).
    """
    if not text.startswith("/"):
        return None
    parts = text[1:].split(maxsplit=1)
    if not parts or not parts[0]:
        return "unknown command — try /help"
    name = parts[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""
    cmd = _COMMANDS.get(name)
    if cmd is None:
        return f"unknown command: /{name} — try /help"
    try:
        return cmd.run(app, args)
    except Exception as exc:  # a handler bug must not kill the input box
        return f"/{name} failed: {type(exc).__name__}: {exc}"


# ── Built-in commands ────────────────────────────────────────────────────────


@command("help", "List available commands")
def _cmd_help(app: AgentApp, args: str) -> str:
    lines = ["Commands:"]
    for name in sorted(_COMMANDS):
        lines.append(f"  /{name} — {_COMMANDS[name].help}")
    return "\n".join(lines)


@command("model", "Show the current model, or /model <name> to switch")
def _cmd_model(app: AgentApp, args: str) -> str:
    """Show the live model, or switch it for subsequent turns.

    The live model is ``provider.MODEL`` — the value the agent loop resolves at
    call time when no per-run override is set (the TUI path). Setting it here
    takes effect on the next model call. The status bar is updated to match.
    """
    import provider

    if not args:
        return f"model: {provider.MODEL}"
    old = provider.MODEL
    provider.MODEL = args
    from tui.components.status_bar import StatusBar

    try:
        app.query_one(StatusBar).set_model(args)
    except Exception:
        pass  # headless/edge: switching still applies even if the bar isn't mounted
    return f"model: {old} → {args}"


@command("usage", "Show session usage: model/tool calls, elapsed, and tokens")
def _cmd_usage(app: AgentApp, args: str) -> str:
    """Report session activity counters plus token totals when available.

    Counters (model calls, tool calls, elapsed) come from the activity panel and
    are always available. Token totals come from app.session_usage, populated
    from each turn's reported usage — blank ("n/a") when the provider reports
    none (e.g. the text-only CLI fork)."""
    from tui.components.activity_panel import ActivityPanel

    lines = ["Usage:"]
    try:
        panel = app.query_one(ActivityPanel)
        lines.append(
            f"  {panel.model_calls} model calls · "
            f"{panel.tool_calls} tool calls · {panel.elapsed_seconds()}s"
        )
    except Exception:
        pass

    usage = getattr(app, "session_usage", None) or {}
    total = usage.get("total_tokens", 0)
    if total:
        lines.append(
            f"  tokens: {total:,} total "
            f"({usage.get('prompt_tokens', 0):,} in / "
            f"{usage.get('completion_tokens', 0):,} out)"
        )
    else:
        lines.append("  tokens: n/a (not reported by the provider)")
    return "\n".join(lines)


@command("skill", "List installed skills, or /skill <name> to load one")
def _cmd_skill(app: AgentApp, args: str) -> str:
    """List all installed skills or load a specific skill's instructions.

    With no argument: list all discovered skills with their descriptions.
    With a skill name: load and display that skill's full instruction body.
    """
    from skills import discover_skills

    skills = discover_skills()

    if not args:
        # List all available skills
        if not skills:
            return "No skills found. Add skills to .claude/skills/<name>/SKILL.md"
        lines = ["Available skills:"]
        for name in sorted(skills):
            skill = skills[name]
            lines.append(f"  {name} — {skill.description}")
        return "\n".join(lines)

    # Load a specific skill
    skill = skills.get(args)
    if skill is None:
        return f"Skill not found: {args}\nRun /skill to list available skills."

    return f"Loaded skill: {args}\n\n{skill.body}"
