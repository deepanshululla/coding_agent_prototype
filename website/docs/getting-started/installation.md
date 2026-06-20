---
sidebar_position: 2
title: Installation
description: Prerequisites, dependency rationale, the src/ import setup, and how to verify the install is working.
---

# Installation

This page covers everything between "I have the repo" and "the code can actually run." The [Quickstart](./quickstart.md) is faster if you just want to run it; come here when something doesn't resolve.

## Prerequisites

| Requirement | Version | Why |
|---|---|---|
| Python | >= 3.14 | Required in `pyproject.toml`; the agent uses modern type syntax throughout |
| `uv` | any recent | Manages the virtualenv and runs scripts via `uv run` |
| Provider API key | — | At least one of `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, or `OPENAI_API_KEY`; see [Configuration](./configuration.md) |

Install `uv` if you don't have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Install dependencies

```bash
uv add litellm python-dotenv
```

### Why these two packages?

**`litellm`** is the entire provider abstraction layer. Pi.dev (the project this mirrors) ships a hand-rolled `packages/ai/` directory with 40+ provider adapters. LiteLLM replaces all of that with a single function call: `litellm.acompletion(model="...", ...)`. Swap the model string, and the provider changes — nothing else touches.

**`python-dotenv`** loads `.env` into `os.environ` at startup. LiteLLM then reads `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, and other standard env vars automatically, with no explicit client construction.

### What is *not* a dependency

Everything else the agent needs is Python's standard library:

| Module | Used for |
|---|---|
| `asyncio` | The agent loop and parallel tool execution |
| `subprocess` | `bash`, `grep`, `find_files` tool implementations |
| `pathlib` | `read_file`, `write_file` tool implementations |
| `glob` | File pattern matching |
| `json` | Parsing tool-call argument fragments after streaming |
| `os`, `sys` | Environment, path manipulation |
| `dataclasses` | `ToolCall` and `ToolResult` in `src/types_.py` |
| `concurrent.futures` | Available as a fallback; primary parallelism uses `asyncio.gather` |

## The `src/` import setup

`src/` is **not a package** — there is no `__init__.py`. This is intentional; it keeps the layout flat and readable. But it means Python won't find `src/agent.py` on the default `sys.path`.

Two ways to handle this:

**Option A — `sys.path` in `main.py`** (used in the current implementation):

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

from agent import run_agent  # works after the insert
```

**Option B — `pyproject.toml` for tests** (needed so `pytest` can import from `src/`):

```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
```

Both approaches are intentional — `main.py` handles its own path; `pyproject.toml` handles the test runner's path.

:::note
Neither approach installs the code as a package. This is fine for a learning project. If you wanted to distribute it, you'd add a proper `src/coding_agent/__init__.py` and set `[tool.setuptools.packages]` in `pyproject.toml`.
:::

## Verify the install

After `uv add litellm python-dotenv`, confirm the critical imports resolve:

```bash
uv run python -c "import litellm; import dotenv; print('OK')"
```

Expected output: `OK`

Then confirm the agent module itself is importable (requires the `sys.path` insert in `main.py` to be present):

```bash
uv run python -c "
import sys, pathlib
sys.path.insert(0, str(pathlib.Path('src').resolve()))
from agent import run_agent
print('agent imported OK')
"
```

If either command fails with an `ImportError`, check:
1. `uv add litellm python-dotenv` completed without errors
2. You're running from the repo root (not from inside `src/`)
3. The `sys.path` insert appears before the `from agent import ...` line in `main.py`

## Next steps

- [Configuration](./configuration.md) — set your API key and pick a model
- [Quickstart](./quickstart.md) — run your first task
