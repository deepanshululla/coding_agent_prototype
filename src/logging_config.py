"""Loguru setup for the coding agent.

Call setup_logging() once in main.py, before any other src import.
All other modules import `logger` from this module — do not create
separate loguru loggers.

Two channels:
  stdout  — model streamed text + tool markers (managed by agent.py print() calls)
  stderr  — diagnostics: tool lifecycle, iteration counts, errors (loguru)

With AGENT_LOG_LEVEL=DEBUG you see every tool call on stderr while
stdout shows only the model's response.
"""

import os
import sys

from loguru import logger

_configured = False


def setup_logging() -> None:
    """Configure loguru. Idempotent — safe to call more than once."""
    global _configured
    if _configured:
        return

    # Remove loguru's default handler (writes to stderr with its own format).
    logger.remove()

    level = os.environ.get("AGENT_LOG_LEVEL", "INFO").upper()
    log_file = os.environ.get("AGENT_LOG_FILE")

    # In TUI mode (AGENT_UI=tui) Textual owns the terminal. loguru writes to
    # stderr — that same terminal — so every diagnostic line would be painted
    # into the middle of the rendered frame and corrupt the display. Route
    # diagnostics to a file instead (AGENT_LOG_FILE, or a default under /tmp),
    # never to stderr.
    if os.environ.get("AGENT_UI", "stdout") == "tui":
        logger.add(
            log_file or "/tmp/agent-tui.log",
            level=level,
            rotation="10 MB",
            retention=5,
        )
    else:
        # stderr sink — human-readable, coloured.
        logger.add(
            sys.stderr,
            level=level,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | "
            "<cyan>{name}</cyan> - {message}",
            colorize=True,
        )

        # Optional file sink — rotating JSON for log aggregators.
        if log_file:
            logger.add(
                log_file,
                level=level,
                rotation="10 MB",
                retention=5,
                serialize=True,  # one JSON object per line
            )

    logger.debug("logging configured at level {}", level)
    _configured = True


__all__ = ["logger", "setup_logging"]
