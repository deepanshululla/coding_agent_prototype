---
sidebar_position: 2
title: Termux on Android
description: Running the coding agent in Termux on Android — package installation, API key setup, and known limitations.
---

# Termux on Android

Termux gives you a real Linux environment on Android. The agent runs there with a few caveats around subprocess availability and storage access.

---

## Install prerequisites

Open Termux and install Python and the standard build tools:

```bash
pkg update && pkg upgrade
pkg install python python-pip
```

Then install `uv`:

```bash
pip install uv
```

:::tip
If `pip install uv` is slow or fails, try `pip install --upgrade pip` first, then retry. Alternatively, install via the official script if `curl` is available:

```bash
pkg install curl
curl -LsSf https://astral.sh/uv/install.sh | sh
```
:::

---

## Clone the repo and install dependencies

```bash
pkg install git
git clone https://github.com/<your-fork>/coding-agent-from-scratch
cd coding-agent-from-scratch
uv add litellm python-dotenv
```

---

## Set the API key

Create a `.env` file at the repo root:

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

Or export it for the current session:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## Run the agent

```bash
uv run main.py "list all .py files in src/"
```

Output streams to the Termux terminal. Since the agent is stdout-only (no TUI), it works well in a plain terminal.

---

## Known limitations

### Subprocess availability

The `bash` tool calls `subprocess.run(cmd, shell=True, ...)`. Termux has a real shell (`bash` or `sh`) and most common tools (`grep`, `find`, `ls`, `cat`) are available after `pkg install`. The agent's `grep` and `find_files` tools should work, but some commands that rely on system binaries (`systemctl`, `apt`, etc.) are not available in Termux.

### Storage access

By default, Termux only has access to its own internal storage directory. If you want the agent to read and edit files in your Android shared storage (e.g. `Downloads/`):

```bash
termux-setup-storage
```

This prompts for storage permission and mounts shared storage at `~/storage/`. File paths like `~/storage/downloads/myproject/` then work in tool calls.

### No `asyncio.to_thread` issues

Python's `asyncio.to_thread` is available in Python 3.9+. Termux ships a recent Python version, so blocking-I/O wrapping in the tool functions works as expected.

### Memory constraints

Android may kill the Termux process if the device is under memory pressure during long-running tasks. For tasks involving many file reads and LLM calls, consider running the agent in a `tmux` session (see [tmux](./tmux.md)) so you can reattach if the terminal is interrupted.

### Long output

The terminal in Termux has a limited scroll buffer. For tasks that produce a lot of output, redirect to a file:

```bash
uv run main.py "audit all .py files for type hints" | tee output.txt
```

---

## Related pages

- [Installation](../getting-started/installation.md) — general setup steps
- [tmux](./tmux.md) — keep the agent running in a detachable session
- [Shell Aliases](./shell-aliases.md) — convenient launch shortcuts
