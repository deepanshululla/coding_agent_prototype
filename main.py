"""CLI entrypoint.

Usage:
    uv run main.py "add type hints to all functions in tools.py"

With no argument, prompts for a task interactively. Set AGENT_UI=tui to
launch the full-screen Textual UI; the default (stdout) streams to the
terminal exactly as before.

Pass --sandbox as the first argument to run the agent inside a throwaway git
worktree (Layer 12.4); the agent's writes land on a fresh branch and your main
working tree is untouched. The post-run hint shows how to review, merge, or
discard the result.
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# src/ is not a package; make its modules importable.
sys.path.insert(0, str(Path(__file__).parent / "src"))


def _extract_skills(args: list[str]) -> tuple[list[str], list[str] | None]:
    """Pull a ``--skills`` flag out of ``args``, returning the remaining args
    (the task tokens) and the resolved skill list.

    The flag accepts comma- *or* space-separated skill names that immediately
    follow it, stopping at the first token that is itself a flag (starts with
    ``--``) or that contains whitespace — a whitespace-bearing token is taken to
    be the task string, not a skill name. This keeps a multi-word task that
    follows ``--skills`` unambiguous, e.g.::

        main.py --skills explain "walk me through the loop"

    Returns ``None`` for the skill list when the flag is absent (caller falls
    back to the env-driven ``ACTIVE_SKILLS``); returns ``[]`` when the flag is
    present with no names (a bare prompt).
    """
    if "--skills" not in args:
        return args, None

    idx = args.index("--skills")
    remaining = args[:idx]
    skills: list[str] = []
    rest = args[idx + 1 :]
    i = 0
    while i < len(rest):
        token = rest[i]
        # A flag or a whitespace-bearing token (the task) ends the skill list;
        # everything from here on is a task token, kept verbatim.
        if token.startswith("--") or (token.split() != [token]):
            break
        skills.extend(s.strip() for s in token.split(",") if s.strip())
        i += 1
    remaining.extend(rest[i:])
    return remaining, skills


def _extract_model(args: list[str]) -> tuple[list[str], str | None]:
    """Pull a ``--model`` flag out of ``args`` (Phase 13.6).

    ``--model <name>`` selects the provider/model for this run, overriding the
    ``AGENT_MODEL`` env var. The single token that follows the flag is the model
    string (e.g. ``gpt-4o``, ``gemini/gemini-2.0-flash``); it is removed from the
    arg list so it is not mistaken for part of the task. Returns the remaining
    args and the model (``None`` when the flag is absent, falling back to the
    configured ``MODEL``).
    """
    if "--model" not in args:
        return args, None

    idx = args.index("--model")
    model = args[idx + 1] if idx + 1 < len(args) else None
    remaining = args[:idx] + args[idx + 2 :]
    return remaining, model


def _extract_dir(args: list[str]) -> tuple[list[str], str | None]:
    """Pull a ``--dir`` flag out of ``args``.

    ``--dir <path>`` selects the folder the agent works in for this run (TUI or
    stdout). The single token that follows the flag is the path; it is removed
    from the arg list so it is not mistaken for part of the task. Returns the
    remaining args and the path (``None`` when the flag is absent, leaving the
    process working directory unchanged).
    """
    if "--dir" not in args:
        return args, None

    idx = args.index("--dir")
    directory = args[idx + 1] if idx + 1 < len(args) else None
    remaining = args[:idx] + args[idx + 2 :]
    return remaining, directory


def _extract_hot_reload(args: list[str]) -> tuple[list[str], bool]:
    """Pull a ``--hot-reload`` flag out of ``args``.

    ``--hot-reload`` enables hot reload mode for the TUI. Returns the remaining
    args and True if the flag is present, False otherwise.
    """
    if "--hot-reload" not in args:
        return args, False

    idx = args.index("--hot-reload")
    remaining = args[:idx] + args[idx + 1 :]
    return remaining, True


def _should_enable_hot_reload(flag: bool) -> bool:
    """Check if hot reload should be enabled based on flag or env var.

    The --hot-reload flag takes precedence; otherwise check AGENT_HOT_RELOAD=1.
    """
    if flag:
        return True
    return os.getenv("AGENT_HOT_RELOAD", "").strip() == "1"


def _resolve_dir(path: str) -> str:
    """Validate ``path`` is an existing directory and return its absolute form.

    Exits with a clear message rather than a traceback when the path is missing
    or is not a directory — a mistyped ``--dir`` should fail fast and legibly.
    """
    p = Path(path).expanduser()
    if not p.exists():
        raise SystemExit(f"--dir: no such directory: {path}")
    if not p.is_dir():
        raise SystemExit(f"--dir: not a directory: {path}")
    return str(p.resolve())


def _initial_task(args: list[str], ui: str) -> str:
    """Resolve the initial task string.

    Args on the command line are always used. With none, the stdout path prompts
    on stdin (interactive use), but the TUI returns "" — it launches idle and
    waits for the first message typed into the input box, so it must never block
    on input() before the full-screen UI takes over the terminal.
    """
    if args:
        return " ".join(args)
    if ui == "tui":
        return ""
    return input("Task: ")


def main() -> None:
    load_dotenv()

    # Configure loguru before importing any module that imports `logger`.
    # Reads AGENT_LOG_LEVEL (default INFO); diagnostics go to stderr.
    from logging_config import setup_logging

    setup_logging()

    args = sys.argv[1:]

    # --skills (Layer 13.3): activate a named set of instruction blocks for this
    # session. Consumes the values that follow it until the next flag or end of
    # argv, and overrides the AGENT_SKILLS env var. `active_skills is None` means
    # "fall back to ACTIVE_SKILLS"; an empty list means "no skills" (bare prompt).
    args, active_skills = _extract_skills(args)

    # --model (Layer 13.6): pick the provider/model for this run, overriding the
    # AGENT_MODEL env var. `model is None` falls back to the configured MODEL.
    args, model = _extract_model(args)

    # --dir: point the agent at a working folder. Applied with os.chdir before
    # anything reads the cwd, so every tool (read_file, bash, grep, list_dir) and
    # the system prompt's "Working directory" line resolve against it.
    args, directory = _extract_dir(args)
    if directory is not None:
        os.chdir(_resolve_dir(directory))

    # --hot-reload: enable TUI hot reload mode for rapid iteration.
    args, hot_reload_flag = _extract_hot_reload(args)
    hot_reload = _should_enable_hot_reload(hot_reload_flag)

    # --sandbox: run inside a throwaway git worktree (Layer 12.4). The flag must
    # be the first argument; everything after it is the task.
    if args and args[0] == "--sandbox":
        task = " ".join(args[1:]) if len(args) > 1 else input("Task: ")
        if not task.strip():
            print("No task provided.")
            return
        from sandbox import run_in_worktree

        worktree = asyncio.run(run_in_worktree(task))
        run_id = worktree.name.split("-")[-1]
        print(f"\n--- Agent finished in worktree: {worktree}")
        print(f"    Review:  git -C {worktree} diff HEAD")
        print(f"    Merge:   git merge agent/task-{run_id}")
        print(f"    Discard: git worktree remove {worktree} --force")
        return

    ui = os.getenv("AGENT_UI", "stdout")
    task = _initial_task(args, ui)
    # The TUI may start with no task (it waits for input); stdout needs one.
    if ui != "tui" and not task.strip():
        print("No task provided.")
        return

    # Fold project instructions (AGENTS.md / CLAUDE.md, Layer 13.1) into the
    # system prompt so the agent starts each session briefed on repo conventions.
    from project_instructions import load_project_instructions

    cwd = os.getcwd()

    # Per-session override (Layer 13.2): AGENT_SESSION_CONTEXT injects extra
    # context for just this run, composed alongside the always-on project
    # instructions. Both land at the bottom of the system prompt via extra=.
    session_override = os.environ.get("AGENT_SESSION_CONTEXT", "")
    extra = "\n\n".join(filter(None, [load_project_instructions(cwd), session_override]))

    if ui == "tui":
        # The TUI path keeps its own prompt build; MCP wiring lives on the
        # stdout path (Layer 13.5) where session lifecycle is easy to manage.
        from tui import run

        run(task, hot_reload=hot_reload)
    else:
        asyncio.run(_run_stdout(task, cwd=cwd, extra=extra, skills=active_skills, model=model))


async def _run_stdout(
    task: str,
    *,
    cwd: str,
    extra: str,
    skills: list[str] | None,
    model: str | None = None,
) -> None:
    """Run the agent on the stdout path with MCP servers wired in.

    MCP servers (Layer 13.5) are connected *before* the system prompt is built
    so their tools are merged into TOOLS_SCHEMA before the first API call. The
    try/finally guarantees every session is closed even if the run raises.
    """
    from agent import run_agent
    from hooks import log_after_tool_call
    from mcp_client import load_mcp_servers
    from prompts import build_system_prompt

    sessions = await load_mcp_servers()
    try:
        system_prompt = build_system_prompt(cwd=cwd, extra=extra, skills=skills)
        await run_agent(
            task,
            system_prompt=system_prompt,
            after_tool_call=log_after_tool_call,
            model=model,
        )
    finally:
        for session in sessions:
            await session.aclose()


if __name__ == "__main__":
    main()
