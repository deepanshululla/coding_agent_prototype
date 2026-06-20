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


def main() -> None:
    load_dotenv()

    # Configure loguru before importing any module that imports `logger`.
    # Reads AGENT_LOG_LEVEL (default INFO); diagnostics go to stderr.
    from logging_config import setup_logging

    setup_logging()

    args = sys.argv[1:]

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

    task = " ".join(args) if args else input("Task: ")
    if not task.strip():
        print("No task provided.")
        return

    # Fold project instructions (AGENTS.md / CLAUDE.md, Layer 13.1) into the
    # system prompt so the agent starts each session briefed on repo conventions.
    from project_instructions import load_project_instructions
    from prompts import build_system_prompt

    cwd = os.getcwd()
    system_prompt = build_system_prompt(
        cwd=cwd,
        extra=load_project_instructions(cwd),
    )

    if os.getenv("AGENT_UI", "stdout") == "tui":
        from tui import run

        run(task)
    else:
        from agent import run_agent

        asyncio.run(run_agent(task, system_prompt=system_prompt))


if __name__ == "__main__":
    main()
