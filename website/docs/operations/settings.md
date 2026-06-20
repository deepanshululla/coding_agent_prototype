---
sidebar_position: 3
title: Settings Reference
description: Every tunable in the agent — model, limits, tools, allowlist, skills, UI, MCP — and the AGENT_* environment variables that configure them.
---

# Settings Reference

Every knob in the agent has two faces: a **module-level constant** (the default, defined in
the source) and an **`AGENT_*` environment variable** that overrides it at startup. Set the
env vars in `.env` (loaded by `python-dotenv` in `main.py`) or export them in your shell.

:::note Status
The shipped `src/*.py` files read literal module constants today (e.g. `MODEL = "claude-sonnet-4-5"`,
`MAX_ITERATIONS = 30`). The `AGENT_*` environment layer described here is the **supported way
to make those configurable** — a thin `src/config.py` reader whose defaults equal the shipped
constants. Provider API keys are already read from the environment by LiteLLM. The
feature-specific vars (`AGENT_BASH_ALLOWLIST`, `AGENT_SKILLS`, `AGENT_UI`, `AGENT_MCP_CONFIG`)
are documented on their feature pages, linked below.
:::

## All environment variables

| Variable | Overrides | Default | Type |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | — (LiteLLM auth) | _(none)_ | secret |
| `OPENAI_API_KEY` | — (LiteLLM auth) | _(none)_ | secret |
| `GEMINI_API_KEY` | — (LiteLLM auth) | _(none)_ | secret |
| `USE_CLAUDE_CLI_LLM` | LLM backend (route via `claude -p`) | _(unset = LiteLLM)_ | `1` to enable |
| `AGENT_MODEL` | `MODEL` (`provider.py`) | `claude-sonnet-4-5` | string |
| `AGENT_MAX_TOKENS` | `MAX_TOKENS` (`provider.py`) | `8096` | int |
| `AGENT_MAX_ITERATIONS` | `MAX_ITERATIONS` (`agent.py`) | `30` | int |
| `AGENT_BASH_TIMEOUT` | `BASH_TIMEOUT` (`tools.py`) | `30` | int (seconds) |
| `AGENT_BASH_OUTPUT_LIMIT` | `BASH_OUTPUT_LIMIT` (`tools.py`) | `10000` | int (chars) |
| `AGENT_FIND_LIMIT` | `FIND_LIMIT` (`tools.py`) | `200` | int |
| `AGENT_READ_LIMIT` | `read_file` default `limit` (`tools.py`) | `2000` | int |
| `AGENT_SYSTEM_PROMPT_EXTRA` | `extra` in `build_system_prompt` | `""` | string |
| `AGENT_BASH_ALLOWLIST` | command allowlist | _(unset = no gate)_ | csv |
| `AGENT_PERMISSION_MODE` | tool-approval mode | `auto` | `auto`/`prompt`/`deny` |
| `AGENT_SKILLS` | active skills | `tdd,git` | csv |
| `AGENT_SKILLS_DIR` | skills directory | `src/skills` | path |
| `AGENT_CLAUDE_SKILLS` | read installed Agent Skills from `~/.claude` | _(unset = off)_ | `1` to enable |
| `AGENT_UI` | front-end | `stdout` | `stdout`/`tui` |
| `AGENT_THEME` | TUI theme | `dark` | string |
| `AGENT_MCP_CONFIG` | MCP server config file | _(unset = no MCP)_ | path |
| `AGENT_HTTP_HOST` | HTTP server bind address (Granian) | `127.0.0.1` | host |
| `AGENT_HTTP_PORT` | HTTP server port (Granian) | `8000` | int |
| `AGENT_INSTRUCTIONS_FILES` | project instruction files to load | `AGENTS.md,CLAUDE.md` | csv |
| `AGENT_LOG_LEVEL` | log verbosity (loguru) | `INFO` | level |
| `AGENT_LOG_FILE` | rotating JSON log file path | _(unset = stderr only)_ | path |

Feature-specific vars are covered in depth on their own pages:
[Command Allowlist](./command-allowlist.md) · [Permissions](./permissions.md) ·
[Skills](../customization/skills.md) · [Installing Agent Skills](../customization/installing-claude-skills.md) ·
[Reading Installed Skills](../customization/reading-installed-skills.md) ·
[Project Instructions](../customization/project-instructions.md) · [Logging](./logging.md) ·
[Terminal UI](../terminal-ui/overview.md) · [MCP](../mcp/overview.md).

## The config reader

Centralize the reads in one module so every other file imports resolved values instead of
calling `os.environ` ad hoc. Defaults match the shipped constants, so behavior is identical
when nothing is set.

```python
# src/config.py
import os


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"{name} must be an integer, got {raw!r}")


def _csv(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


# Model / provider
MODEL = os.environ.get("AGENT_MODEL", "claude-sonnet-4-5")
MAX_TOKENS = _int("AGENT_MAX_TOKENS", 8096)

# Loop
MAX_ITERATIONS = _int("AGENT_MAX_ITERATIONS", 30)
SYSTEM_PROMPT_EXTRA = os.environ.get("AGENT_SYSTEM_PROMPT_EXTRA", "")

# Tools
BASH_TIMEOUT = _int("AGENT_BASH_TIMEOUT", 30)
BASH_OUTPUT_LIMIT = _int("AGENT_BASH_OUTPUT_LIMIT", 10_000)
FIND_LIMIT = _int("AGENT_FIND_LIMIT", 200)
READ_LIMIT = _int("AGENT_READ_LIMIT", 2000)

# Features
BASH_ALLOWLIST = _csv("AGENT_BASH_ALLOWLIST", [])
PERMISSION_MODE = os.environ.get("AGENT_PERMISSION_MODE", "auto")
SKILLS = _csv("AGENT_SKILLS", ["tdd", "git"])
SKILLS_DIR = os.environ.get("AGENT_SKILLS_DIR", "src/skills")
UI = os.environ.get("AGENT_UI", "stdout")
THEME = os.environ.get("AGENT_THEME", "dark")
MCP_CONFIG = os.environ.get("AGENT_MCP_CONFIG")  # None = MCP disabled
```

Then each module imports from `config` instead of hard-coding:

```python
# src/provider.py
from config import MODEL, MAX_TOKENS

# src/agent.py
from config import MAX_ITERATIONS

# src/tools.py
from config import BASH_TIMEOUT, BASH_OUTPUT_LIMIT, FIND_LIMIT
```

`load_dotenv()` in `main.py` must run **before** `config` is imported, so `.env` is in
`os.environ` when these module-level reads happen. Import `config` from inside `main()` (after
`load_dotenv()`), or keep `load_dotenv()` at the top of `main.py` before any `src` import.

:::tip Fail closed on bad input
`_int` raises `SystemExit` on a non-integer so a typo (`AGENT_MAX_ITERATIONS=lots`) stops the
run with a clear message instead of silently falling back to a default. Security-sensitive
vars (`AGENT_BASH_ALLOWLIST`) default to the **safe** value (empty) so a missing config never
opens a hole. See [Command Allowlist](./command-allowlist.md).
:::

## Model and provider

`AGENT_MODEL` / `MODEL` is a single string that selects both provider and model — LiteLLM
routes on the prefix:

```python
MODEL = "claude-sonnet-4-5"          # Anthropic
MODEL = "gemini/gemini-2.0-flash"    # Google
MODEL = "gpt-4o"                     # OpenAI
```

**When to change it:** a cheaper/faster model for high-iteration development; a stronger model
for complex refactors. All work identically — LiteLLM normalizes the response. Set the
matching `*_API_KEY`. See [Providers & Models](../getting-started/providers-and-models.md).

## Token and response limits

`AGENT_MAX_TOKENS` / `MAX_TOKENS` (default `8096`) caps tokens generated **per turn**, passed
straight to `litellm.acompletion(..., max_tokens=...)`. Raise it if the agent truncates on
long file writes; lower it to cap cost. Note a 30-iteration session can generate up to
`30 × MAX_TOKENS` output tokens.

## Agent loop limits

`AGENT_MAX_ITERATIONS` / `MAX_ITERATIONS` (default `30`) is the hard cap on inner-loop cycles:

```python
while (has_more_tool_calls or pending_messages) and iteration < MAX_ITERATIONS:
    iteration += 1
    ...
```

Lower to `5–10` for tight, exploratory tasks; raise above `30` only for long-horizon tasks in
a [containerized](./containerization.md) environment. The loop exits **silently** at the cap —
if the agent stops early on a hard task, check whether it hit the limit.

## Bash tool limits

| Setting | Env var | Default | Controls |
|---|---|---|---|
| `BASH_TIMEOUT` | `AGENT_BASH_TIMEOUT` | `30` s | How long one shell command may run before it's killed |
| `BASH_OUTPUT_LIMIT` | `AGENT_BASH_OUTPUT_LIMIT` | `10000` chars | Max characters returned; output beyond this is truncated |

```python
# src/tools.py
BASH_TIMEOUT = 30
BASH_OUTPUT_LIMIT = 10_000

async def bash(command: str) -> str:
    def _run():
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=BASH_TIMEOUT,
        )
        out = proc.stdout + ("\n" if proc.stdout and proc.stderr else "") + proc.stderr
        return f"(exit code {proc.returncode})\n{_truncate(out, BASH_OUTPUT_LIMIT)}".rstrip()
    return await asyncio.to_thread(_run)
```

Raise the timeout for legitimately slow commands (large test suites, builds). Raise the output
cap if the agent loses important output; lower it to save context. Truncation is silent — the
agent sees a partial result.

## File tool limits

| Setting | Env var | Default | Controls |
|---|---|---|---|
| `FIND_LIMIT` | `AGENT_FIND_LIMIT` | `200` | Max paths returned by `find_files` |
| `read_file` `limit` | `AGENT_READ_LIMIT` | `2000` | Default max lines per `read_file` (callers may override per call) |
| `read_file` `offset` | — | `0` | Default start line (per-call argument) |

`find_files` caps results to avoid flooding the context window in a large monorepo. The
`read_file` defaults only apply when the model omits `offset`/`limit` — it can always pass its
own. See [Built-in Tools](../tools/built-in-tools.md).

## Provider keys

| Variable | Required for |
|---|---|
| `ANTHROPIC_API_KEY` | `claude-*` models |
| `OPENAI_API_KEY` | `gpt-*` models |
| `GEMINI_API_KEY` | `gemini/*` models |

LiteLLM reads these automatically — no explicit client setup in `provider.py`. See the
[LiteLLM provider docs](https://docs.litellm.ai/docs/providers) for the full list.

:::warning
Don't add database passwords, deploy keys, or unrelated credentials to `.env`. The agent can
read environment variables via `bash`. Scope the environment to one API key per provider you
use. See [Security Model](./security.md).
:::

## Example `.env`

```bash
# Provider auth
ANTHROPIC_API_KEY=sk-ant-...

# Model + limits
AGENT_MODEL=claude-sonnet-4-5
AGENT_MAX_TOKENS=8096
AGENT_MAX_ITERATIONS=30

# Tool limits
AGENT_BASH_TIMEOUT=30
AGENT_BASH_OUTPUT_LIMIT=10000
AGENT_FIND_LIMIT=200

# Features
AGENT_BASH_ALLOWLIST=ls,cat,git,pytest,python
AGENT_PERMISSION_MODE=prompt
AGENT_SKILLS=tdd,git
AGENT_UI=tui
AGENT_THEME=dark
AGENT_MCP_CONFIG=mcp.json
```

## Quick reference

| What you want to do | Variable |
|---|---|
| Use a different model/provider | `AGENT_MODEL` |
| Allow longer responses | `AGENT_MAX_TOKENS` |
| Stop sooner / run longer | `AGENT_MAX_ITERATIONS` |
| Allow long-running shell commands | `AGENT_BASH_TIMEOUT` |
| See more shell output | `AGENT_BASH_OUTPUT_LIMIT` |
| Read more lines per file by default | `AGENT_READ_LIMIT` |
| Search a large monorepo | `AGENT_FIND_LIMIT` |
| Restrict which commands `bash` may run | `AGENT_BASH_ALLOWLIST` |
| Require approval before tool calls | `AGENT_PERMISSION_MODE` |
| Choose active skills | `AGENT_SKILLS` |
| Read Agent Skills already installed on the machine | `AGENT_CLAUDE_SKILLS=1` |
| Use the full-screen terminal UI | `AGENT_UI=tui` |
| Connect external tool servers | `AGENT_MCP_CONFIG` |
| Serve the agent over HTTP (FastAPI on Granian) | `AGENT_HTTP_HOST` / `AGENT_HTTP_PORT` |
| Load project instructions (AGENTS.md / CLAUDE.md) | `AGENT_INSTRUCTIONS_FILES` |
| Change log verbosity or write a log file | `AGENT_LOG_LEVEL` / `AGENT_LOG_FILE` |
| Authenticate with a provider | the relevant `*_API_KEY` |
