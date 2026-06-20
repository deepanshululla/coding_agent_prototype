---
sidebar_position: 3
title: tmux
description: Running the agent in a tmux pane for long tasks — how to create a session, detach, reattach, and watch streamed output.
---

# tmux

Long-running agent tasks — refactoring a whole module, running a test suite in a loop, auditing many files — benefit from running inside a tmux session. If your SSH connection drops or you close the terminal, the agent keeps running and you can reattach later to see the streamed output.

---

## Quick start

### Create a named session and start the agent

```bash
tmux new-session -s agent
uv run main.py "refactor all tool functions to use asyncio.to_thread"
```

The agent's output streams to the pane as it runs.

### Detach without stopping the agent

Press `Ctrl-b d` (hold Ctrl, tap b, release both, tap d). You return to your normal shell. The agent keeps running in the background.

### Reattach later

```bash
tmux attach-session -t agent
```

You see the pane exactly as it was, including all output that was printed while you were away.

### List active sessions

```bash
tmux ls
```

---

## Watching output from outside the pane

If you want to tail the agent's output from a second terminal without attaching:

```bash
# Redirect output to a file when launching
tmux new-session -d -s agent -x 220 -y 50
tmux send-keys -t agent "uv run main.py 'audit src/' | tee /tmp/agent.log" Enter

# In another terminal, tail the log
tail -f /tmp/agent.log
```

The `-d` flag creates the session detached (no window opens). `send-keys` types the command and presses Enter.

---

## Splitting the window to run tests alongside the agent

```bash
# Start with an agent pane
tmux new-session -s dev

# Split horizontally: Ctrl-b %
# Now you have two panes side by side

# In the left pane: run the agent
uv run main.py "add type hints to tools.py"

# In the right pane (switch with Ctrl-b arrow): run tests in watch mode
uv run pytest tests/test_tools.py -v --tb=short -f
```

This setup lets you watch the agent edit code on the left while tests re-run automatically on the right.

---

## Useful key bindings

| Keys | Action |
|---|---|
| `Ctrl-b d` | Detach from session |
| `Ctrl-b %` | Split pane vertically |
| `Ctrl-b "` | Split pane horizontally |
| `Ctrl-b arrow` | Move between panes |
| `Ctrl-b z` | Zoom current pane to full window |
| `Ctrl-b [` | Enter scroll/copy mode (use arrow keys to scroll) |
| `q` | Exit scroll mode |
| `Ctrl-b $` | Rename session |

---

## Persisting sessions across reboots

By default, tmux sessions die when the system restarts. For long-term persistence, look at [tmux-resurrect](https://github.com/tmux-plugins/tmux-resurrect) or simply note that the agent's conversation is not stored — you restart with a new task anyway.

---

## Related pages

- [Termux on Android](./termux-android.md) — tmux is especially useful on Android where the Termux window may be killed
- [Shell Aliases](./shell-aliases.md) — an alias that launches the agent in a tmux session automatically
