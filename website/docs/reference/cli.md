---
sidebar_position: 6
title: "main.py (CLI)"
description: The command-line entrypoint — loads credentials, reads the task, and runs the agent.
---

# main.py (CLI)

`main.py` is the repo's only entrypoint. It is not inside `src/` — it lives at the repo root so you can run it directly with `uv run`. Its job is minimal: load environment variables, read the task (from the command line or stdin), and hand off to `run_agent`.

:::note
The behavior described here reflects the shipped `main.py`.
:::

---

## Usage

```bash
# Pass the task as a command-line argument
uv run main.py "add type hints to all functions in tools.py"

# Or let main.py prompt you for a task
uv run main.py
# → Task: _
```

The entire task string is constructed by joining `sys.argv[1:]` with spaces, so multi-word tasks do not need special quoting beyond normal shell rules.

---

## `main` (async)

```python
async def main() -> None
```

Top-level async function. Called via `asyncio.run(main())` in the `if __name__ == "__main__"` block.

**Behavior, in order:**

1. **`load_dotenv()`** — reads `.env` from the repo root and injects variables into `os.environ`. This is how `ANTHROPIC_API_KEY` (and any other provider keys) reach LiteLLM without being hard-coded.
2. **Read task** — if `sys.argv[1:]` is non-empty, the task is `" ".join(sys.argv[1:])`. Otherwise, `input("Task: ")` blocks until the user types a task and presses Enter.
3. **`await run_agent(task)`** — delegates to the agent loop in `src/agent.py`. All output (streamed text, tool invocations, results) goes to stdout from inside `run_agent`.

**Returns** `None`.

**Exit behavior** The process exits with code `0` when `run_agent` returns normally (model signaled `stop` or `MAX_ITERATIONS` reached). If `run_agent` raises an uncaught exception (e.g., a network error from LiteLLM), Python exits with a non-zero code and prints the traceback.

---

## Source

```python
import asyncio
import sys
from dotenv import load_dotenv
from agent import run_agent

async def main():
    load_dotenv()
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Task: ")
    await run_agent(task)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## How `src/` is importable

`main.py` imports from `agent` (which is in `src/agent.py`). Since `src/` has no `__init__.py`, it is not a package. Two approaches work:

**Option 1 — `pyproject.toml` (recommended for tests too):**
```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
```

**Option 2 — `sys.path` insertion in `main.py`:**
```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
```

`uv run` picks up `pyproject.toml` configuration automatically, so option 1 keeps `main.py` clean.

---

## Examples

```bash
# Ask the agent to explore the project
uv run main.py "list all Python files and summarize what each one does"

# Ask it to make a targeted change
uv run main.py "add a docstring to every function in src/tools.py"

# Ask it to run tests and report failures
uv run main.py "run the test suite and explain any failures"
```

All output streams to stdout. There is no log file or persistent session in v1.

---

## Related pages

- [agent.py](./agent.md) — `run_agent` that `main.py` delegates to
- [provider.py](./provider.md) — needs `ANTHROPIC_API_KEY` loaded by `load_dotenv()`
- [Getting started](../getting-started/quickstart.md) — installation and first run
