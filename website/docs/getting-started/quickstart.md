---
sidebar_position: 1
title: Quickstart
description: Get the coding agent running in five minutes — clone, install, set your API key, and watch it reason through a real task.
---

# Quickstart

Get the agent running in under five minutes. You'll clone the repo, install two dependencies, set an API key, and watch the agent stream its reasoning as it works.

## Prerequisites

- Python >= 3.14
- [`uv`](https://docs.astral.sh/uv/) (fast Python package manager)
- An API key for at least one provider (Anthropic, Google, or OpenAI)

See [Installation](./installation.md) for a fuller prerequisite checklist.

## Steps

### 1. Clone and enter the repo

```bash
git clone https://github.com/your-org/coding-agent-from-scratch.git
cd coding-agent-from-scratch
```

### 2. Install dependencies

```bash
uv add litellm python-dotenv
```

Two packages. That's it. Everything else (`subprocess`, `pathlib`, `asyncio`, `json`) is stdlib.

### 3. Set your API key

Create a `.env` file at the repo root:

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...
```

LiteLLM reads standard environment variable names automatically — no client setup needed. For other providers, see [Configuration](./configuration.md).

### 4. Run the agent

```bash
uv run main.py "list all .py files"
```

## Expected output

The agent streams its response as it works. You'll see text prose interleaved with tool markers:

```
I'll list all the Python files in the repository.
▸ find_files
  [executing find_files {'dir': '.', 'pattern': '*.py'}]
  [✓ find_files: 312 chars]

Here are all the .py files found:

- main.py
- src/agent.py
- src/tools.py
- src/prompts.py
- src/provider.py
- src/types_.py
- tests/test_tools.py
- tests/test_agent.py
```

Each `▸ tool_name` line appears the moment the model decides to call that tool. Tool arguments and results print immediately after. The agent then resumes streaming prose once all parallel tool calls complete.

:::note
The exact output depends on which files exist in your working directory at run time. The agent sees the actual filesystem.
:::

## What just happened

1. `main.py` loaded `.env`, assembled the task string from `sys.argv`, and called `asyncio.run(run_agent(task))`.
2. `run_agent()` in `src/agent.py` built a system prompt (with your current working directory and today's date), sent the task to the model via `litellm.acompletion(..., stream=True)`, and entered the agent loop.
3. The model responded with a `find_files` tool call. The loop executed it, pushed the result back as a `role: "tool"` message, and re-prompted.
4. The model produced its final text answer and stopped (`finish_reason: "stop"`), so the loop exited.

The loop caps at `MAX_ITERATIONS = 30` — it cannot run forever.

## Next steps

- [Installation](./installation.md) — prerequisites and import setup in detail
- [Configuration](./configuration.md) — provider env vars, model selection, `MAX_ITERATIONS`
- [Your First Task](./first-task.md) — a realistic end-to-end walkthrough with code edits and test runs
