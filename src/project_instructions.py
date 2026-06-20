"""Discover and load AGENTS.md / CLAUDE.md instruction files.

Walks from ``cwd`` up to the git root collecting every matching instruction
file, deduplicating symlinked files by resolved path. The result is a formatted
string meant for ``build_system_prompt(extra=...)`` so each session starts
briefed on the repo's conventions.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_DEFAULT_FILES = ["AGENTS.md", "CLAUDE.md"]


def _git_root(cwd: str) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _candidate_dirs(cwd: str) -> list[Path]:
    """Return [cwd, ..., git_root] — nearest first."""
    start = Path(cwd).resolve()
    root_str = _git_root(cwd)
    root = Path(root_str).resolve() if root_str else start

    dirs: list[Path] = []
    current = start
    while True:
        dirs.append(current)
        if current == root:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return dirs


def load_project_instructions(cwd: str) -> str:
    """Discover instruction files in cwd (and parents up to the git root).

    Returns a formatted string for ``build_system_prompt(extra=...)``, or ``""``
    if none are found. ``AGENT_INSTRUCTIONS_FILES`` (comma-separated) overrides
    the default filenames; setting it to the empty string disables loading.
    """
    raw = os.environ.get("AGENT_INSTRUCTIONS_FILES", ",".join(_DEFAULT_FILES))
    names = [n.strip() for n in raw.split(",") if n.strip()]
    if not names:
        return ""

    sections: list[str] = []
    seen: set[Path] = set()

    for search_dir in _candidate_dirs(cwd):
        for name in names:
            p = search_dir / name
            resolved = p.resolve()
            if resolved in seen:
                continue
            if p.exists():
                seen.add(resolved)
                content = p.read_text(encoding="utf-8").strip()
                sections.append(f"## Project instructions (from {name})\n\n{content}")

    return ("\n\n".join(sections) + "\n") if sections else ""
