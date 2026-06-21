"""Eval harness for the coding agent.

``src/`` is not a package (no ``__init__.py``); pytest puts it on the path via
``pythonpath`` in pyproject, but a direct ``python -m evals.run`` run does not.
Mirror ``main.py`` and prepend it here so the harness can ``from sdk import ...``
no matter how it's launched.
"""

import sys
from pathlib import Path

_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
