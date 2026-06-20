# src/renderer.py

"""Selects the active renderer based on AGENT_OUTPUT / AGENT_UI and exposes emit().

Import this module; never import a renderer directly from agent code. The active
emitter is chosen at import time by ``_select_emit()`` from two independent env
axes:

  AGENT_OUTPUT=json  → NDJSON: every event is printed as one JSON object per line
                       on stdout. Takes precedence over AGENT_UI.
  AGENT_UI=tui|none|stdout  → human/structured renderers (default: stdout).

``_select_emit()`` is a function (not inline import-time branches) so tests can
re-resolve the emitter under a patched environment without ``importlib.reload``
corrupting module identity for other modules that captured ``renderer.emit``.
"""

import json as _json
import os


def _json_emit(event: dict) -> None:
    """NDJSON emitter: one ``json.loads``-able JSON object per line on stdout."""
    print(_json.dumps(event), flush=True)


def _select_emit():
    """Resolve the active emitter from the environment.

    AGENT_OUTPUT=json wins over AGENT_UI, so log pipelines / streaming HTTP
    clients get structured output regardless of the configured UI. The two axes
    are intentionally independent.
    """
    if os.getenv("AGENT_OUTPUT", "") == "json":
        return _json_emit

    ui = os.getenv("AGENT_UI", "stdout")
    if ui == "tui":
        from tui.emit import emit as _emit  # populated in Layer 10.2

        return _emit
    if ui == "none":
        # RPC / HTTP modes: stdout is a structured response channel, so the
        # streamed model text must not be printed there. See renderer_none.py.
        from renderer_none import emit as _emit

        return _emit
    from renderer_stdout import emit as _emit

    return _emit


emit = _select_emit()
