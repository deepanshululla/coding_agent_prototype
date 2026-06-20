# src/renderer.py

"""Selects the active renderer based on AGENT_UI and exposes emit().

Import this module; never import a renderer directly from agent code.
"""

import os

_UI = os.getenv("AGENT_UI", "stdout")

if _UI == "tui":
    from tui.emit import emit  # noqa: F401 — populated in Layer 10.2
elif _UI == "none":
    # RPC / HTTP modes: stdout is a structured response channel, so the
    # streamed model text must not be printed there. See renderer_none.py.
    from renderer_none import emit  # noqa: F401
else:
    from renderer_stdout import emit  # noqa: F401
