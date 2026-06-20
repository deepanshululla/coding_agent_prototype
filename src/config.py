"""Centralised reader for AGENT_* environment variables.

Every module that needs a tunable imports it from here:
    from config import MAX_ITERATIONS, BASH_TIMEOUT

Defaults match the shipped constants so behaviour is identical when
nothing is set. load_dotenv() in main.py must run before config is
imported so .env is in os.environ when these module-level reads happen.
"""

import os
from pathlib import Path


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as err:
        raise SystemExit(f"{name} must be an integer, got {raw!r}") from err


def _csv(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


# ── Model / provider ─────────────────────────────────────────────────────────
MODEL = os.environ.get("AGENT_MODEL", "claude-sonnet-4-5")
MAX_TOKENS = _int("AGENT_MAX_TOKENS", 8096)

# ── Architecture ──────────────────────────────────────────────────────────────
# The agent control-flow strategy (see architecture.py). Overridable per-run via
# the --architecture CLI flag; unknown names fall back to "reactive".
ARCHITECTURE = os.environ.get("AGENT_ARCHITECTURE", "reactive")

# Extended thinking (Phase 17). When THINKING_BUDGET > 0 the provider asks the
# model to reason in a scratchpad before answering; the budget is the token
# allowance for that reasoning. Disabled by default (0) because each thinking
# turn costs budget_tokens extra even when unused — earn its keep on multi-step
# planning / architectural refactors. THINKING_BUDGET and MAX_TOKENS are both
# also readable via the bare env names THINKING_BUDGET / MAX_TOKENS (the plan's
# names) for convenience.
THINKING_BUDGET = _int("THINKING_BUDGET", _int("AGENT_THINKING_BUDGET", 0))

# ── Loop ─────────────────────────────────────────────────────────────────────
MAX_ITERATIONS = _int("AGENT_MAX_ITERATIONS", 30)
SYSTEM_PROMPT_EXTRA = os.environ.get("AGENT_SYSTEM_PROMPT_EXTRA", "")

# ── Tools ────────────────────────────────────────────────────────────────────
BASH_TIMEOUT = _int("AGENT_BASH_TIMEOUT", 30)
BASH_OUTPUT_LIMIT = _int("AGENT_BASH_OUTPUT_LIMIT", 10_000)
FIND_LIMIT = _int("AGENT_FIND_LIMIT", 200)
READ_LIMIT = _int("AGENT_READ_LIMIT", 2000)

# ── Features ─────────────────────────────────────────────────────────────────
BASH_ALLOWLIST = _csv("AGENT_BASH_ALLOWLIST", [])
PERMISSION_MODE = os.environ.get("AGENT_PERMISSION_MODE", "auto")
UI = os.environ.get("AGENT_UI", "stdout")
THEME = os.environ.get("AGENT_THEME", "dark")
MCP_CONFIG = os.environ.get("AGENT_MCP_CONFIG")

# Ctrl+V image paste in the TUI. A terminal never sends image bytes on Ctrl+V —
# the key is a trigger to read the OS clipboard (see tui/clipboard.py). Enabled
# by default; set AGENT_IMAGE_PASTE=0 to unbind it. IMAGE_MAX_BYTES caps the
# clipboard image we will attach (default 5 MB) so an oversized paste is rejected
# with a hint instead of bloating the request.
IMAGE_PASTE = _bool("AGENT_IMAGE_PASTE", True)
IMAGE_MAX_BYTES = _int("AGENT_IMAGE_MAX_BYTES", 5 * 1024 * 1024)

# Agent memory: persistent memory system that stores memories as markdown files
# in ~/.agent_memory/<project_hash>/. Memories are loaded into the system prompt
# to provide context across conversations.
MEMORY_DIR = Path.home() / ".agent_memory"
MEMORY_ENABLED = _bool("AGENT_MEMORY_ENABLED", True)
MEMORY_MAX_LOAD = _int("AGENT_MEMORY_MAX_LOAD", 10)
