"""CLI entrypoint.

Usage:
    uv run main.py "add type hints to all functions in tools.py"

With no argument, prompts for a task interactively.
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

# src/ is not a package; make its modules importable.
sys.path.insert(0, str(Path(__file__).parent / "src"))

from agent import run_agent  # noqa: E402


async def main() -> None:
    load_dotenv()
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Task: ")
    if not task.strip():
        print("No task provided.")
        return
    await run_agent(task)


if __name__ == "__main__":
    asyncio.run(main())
