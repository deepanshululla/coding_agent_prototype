---
sidebar_position: 1
title: Windows
description: Running the coding agent on Windows — WSL and Git Bash recommendations, uv installation, and path separator considerations.
---

# Windows

The agent runs on Windows, but a few rough edges are worth knowing upfront. The short version: use WSL or Git Bash. Native cmd.exe and PowerShell work for the Python layer but cause friction with the `bash` and `grep`/`find` tools.

---

## The `bash` tool and shell differences

The `bash` tool in `src/tools.py` runs commands via:

```python
subprocess.run(cmd, shell=True, capture_output=True, timeout=30)
```

On Unix, `shell=True` uses `/bin/sh`. On Windows, it uses `cmd.exe`. This means:

- Commands like `grep`, `find`, `ls`, `cat` are not available natively in cmd.exe.
- The `grep` and `find_files` tools shell out to the Unix binaries `grep` and `find`. These do not exist in a plain Windows cmd.exe environment.
- Path separators in tool arguments may need to be backslashes (`\`) rather than forward slashes (`/`), depending on the command being run.

:::warning
If you run the agent in a native cmd.exe or PowerShell session, the `bash`, `grep`, and `find_files` tools will fail with "command not found" or equivalent errors. The agent will see error strings back from these tools and may retry or give up, but it will not work well for file-system tasks.
:::

---

## Recommended: WSL (Windows Subsystem for Linux)

WSL gives you a real Linux shell. Install it once and the agent behaves exactly as documented everywhere else.

```powershell
# In PowerShell (Admin)
wsl --install
```

After WSL is set up, open a WSL terminal and follow the standard [installation guide](../getting-started/installation.md). Everything works as-is.

---

## Alternative: Git Bash

Git Bash ships `grep`, `find`, `ls`, and most of the Unix tools the agent relies on. It is lighter than WSL and sufficient for most tasks.

1. Install [Git for Windows](https://git-scm.com/download/win) — Git Bash is included.
2. Open Git Bash (not cmd or PowerShell).
3. Install `uv` and run the agent from Git Bash.

```bash
# In Git Bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

:::tip
Add `C:\Program Files\Git\usr\bin` to your Windows `PATH` so that `grep` and `find` are available even outside Git Bash. This lets you run the agent from other terminals with partial Unix-tool support.
:::

---

## Installing uv on Windows

If you are using a native Windows terminal (cmd or PowerShell), install `uv` with the official Windows installer:

```powershell
# PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then restart your terminal. Verify with:

```powershell
uv --version
```

In WSL or Git Bash, use the shell installer instead:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Path separators

Windows uses `\` as the path separator; Unix tools expect `/`. When passing file paths to the agent at the command line, use forward slashes — Python's `pathlib` normalizes them on Windows, and the tools use `pathlib.Path` internally:

```bash
# This works
uv run main.py "read the file src/tools.py"

# This may fail depending on how the shell interprets backslashes
uv run main.py "read the file src\tools.py"
```

When the agent constructs paths itself (e.g. via `list_dir` or `find_files`), it will use the OS default. If you pass paths between tools and they come back with backslashes, the agent should handle them — but if you see path-related failures, the separator is a likely culprit.

---

## API key in the environment

Set the key in a `.env` file at the repo root (works cross-platform):

```
ANTHROPIC_API_KEY=sk-ant-...
```

Or export it in your shell:

```bash
# Git Bash / WSL
export ANTHROPIC_API_KEY=sk-ant-...

# PowerShell
$env:ANTHROPIC_API_KEY = "sk-ant-..."

# cmd.exe
set ANTHROPIC_API_KEY=sk-ant-...
```

`python-dotenv` (loaded in `main.py`) reads `.env` regardless of platform.

---

## Related pages

- [Installation](../getting-started/installation.md) — full setup steps
- [Shell Aliases](./shell-aliases.md) — shortcut functions for launching the agent
