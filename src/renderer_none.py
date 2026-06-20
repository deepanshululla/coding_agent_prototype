# src/renderer_none.py

"""Null renderer: swallows every event.

Used by RPC / HTTP modes (AGENT_UI=none) where stdout is a structured
response channel — printing streamed model text there would corrupt the
JSON-RPC / NDJSON payload. The agent loop still emits events; they just go
nowhere. Diagnostics remain on stderr via loguru.
"""


def emit(event: dict) -> None:  # noqa: ARG001 — intentionally ignores the event
    return None
