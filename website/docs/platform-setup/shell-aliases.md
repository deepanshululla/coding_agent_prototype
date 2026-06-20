---
sidebar_position: 4
title: Shell Aliases
description: Shell functions and aliases for launching the agent quickly, setting the API key once in your profile, and switching models at the command line.
---

# Shell Aliases

Typing `uv run /full/path/to/main.py` every time gets old quickly. A shell function cuts that to a single word and lets you pass flags or set the model inline.

---

## Basic function (zsh / bash)

Add this to your `~/.zshrc` or `~/.bashrc`:

```bash
agent() {
  uv run /path/to/coding_agent_from_scratch/main.py "$@"
}
```

Replace `/path/to/coding_agent_from_scratch` with the absolute path to the repo. The `"$@"` passes all arguments through verbatim.

Usage:

```bash
agent "list all .py files in src/"
agent "add type hints to tools.py and run the tests"
```

---

## With model override

If you parameterize the model via `AGENT_MODEL` (see [Swapping Providers](../guides/swapping-providers.md)):

```bash
agent() {
  AGENT_MODEL="${AGENT_MODEL:-claude-sonnet-4-5}" \
    uv run /path/to/coding_agent_from_scratch/main.py "$@"
}

# Per-invocation override
agentflash() {
  AGENT_MODEL=gemini/gemini-2.0-flash agent "$@"
}

agentgpt() {
  AGENT_MODEL=gpt-4o agent "$@"
}
```

Now you can switch models without opening any file:

```bash
agentflash "summarize all docstrings in tools.py"
agentgpt "write tests for the edit_file function"
```

---

## With tmux integration

This variant creates a named tmux session for each task, so long-running tasks survive terminal closure:

```bash
agent() {
  local session="agent-$(date +%s)"
  tmux new-session -d -s "$session" -x 220 -y 50
  tmux send-keys -t "$session" \
    "uv run /path/to/coding_agent_from_scratch/main.py $(printf '%q' "$*")" Enter
  tmux attach-session -t "$session"
}
```

When you close the terminal, the agent keeps running. Reattach with `tmux attach-session -t <session-name>` (find the name with `tmux ls`).

---

## Setting the API key once in your shell profile

Add the key to your profile so you never need to type it or maintain a `.env` file:

```bash
# ~/.zshrc or ~/.bashrc
export ANTHROPIC_API_KEY="sk-ant-..."
```

:::warning
Your shell profile is readable by any process running as your user. For shared machines or CI environments, prefer a `.env` file in the repo root (which `python-dotenv` loads automatically) or a secrets manager. Never commit API keys to the repo.
:::

If you use multiple providers, export all of them and let the model string in `provider.py` determine which one is used:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export GEMINI_API_KEY="..."
export OPENAI_API_KEY="sk-..."
```

LiteLLM picks the right key based on the model prefix. Unused keys are harmlessly ignored.

---

## Applying changes

After editing `~/.zshrc` or `~/.bashrc`:

```bash
source ~/.zshrc
# or
source ~/.bashrc
```

Verify the function is loaded:

```bash
type agent
# agent is a shell function
```

---

## Related pages

- [tmux](./tmux.md) — running the agent in a detachable session
- [Swapping Providers](../guides/swapping-providers.md) — parameterizing the model via `AGENT_MODEL`
- [Installation](../getting-started/installation.md) — full setup steps
