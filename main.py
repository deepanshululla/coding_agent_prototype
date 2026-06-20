"""CLI entrypoint.

Usage:
    uv run main.py "add type hints to all functions in tools.py"

With no argument, prompts for a task interactively. Set AGENT_UI=tui to
launch the full-screen Textual UI; the default (stdout) streams to the
terminal exactly as before.
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
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Task: ")
    if not task.strip():
        print("No task provided.")
        return

    if os.getenv("AGENT_UI", "stdout") == "tui":
        from tui import run

        run(task)
    else:
        from agent import run_agent

        asyncio.run(run_agent(task))


if __name__ == "__main__":
    main()
