"""Discover local Ollama models and map them to chat-capable model ids.

Two pieces, split so the parsing/filtering is pure (and unit-tested without a
server): :func:`fetch_ollama_tags` does the one HTTP call to ``/api/tags``, and
:func:`chat_models` turns that JSON into the ``ollama_chat/<name>`` ids the eval
runner feeds to the agent.

The ``ollama_chat/`` prefix is deliberate: it routes through litellm to Ollama's
``/api/chat`` endpoint, the only one that supports tool calling. The bare
``ollama/`` prefix hits ``/api/generate``, which silently ignores tools — useless
for a tool-calling eval.
"""

from __future__ import annotations

import json
import urllib.request

#: Substrings that mark a model as an embedding model (no chat / tool calling),
#: so they're excluded from a tool-calling eval.
_EMBEDDING_MARKERS = ("embed", "bge-m3")

DEFAULT_BASE_URL = "http://localhost:11434"


def chat_models(tags: dict, *, exclude_markers: tuple[str, ...] = _EMBEDDING_MARKERS) -> list[str]:
    """Map an Ollama ``/api/tags`` payload to sorted ``ollama_chat/<name>`` ids.

    Embedding models (matched by ``exclude_markers`` against the lowercased name)
    are dropped — they can't chat or call tools. A name that already carries an
    ``ollama_chat/`` prefix is kept as-is; otherwise the prefix is added. The
    result is de-duplicated and sorted for stable output.
    """
    out: set[str] = set()
    for entry in (tags or {}).get("models", []):
        name = (entry or {}).get("name", "")
        if not name:
            continue
        bare = name.removeprefix("ollama_chat/").removeprefix("ollama/")
        if any(marker in bare.lower() for marker in exclude_markers):
            continue
        out.add(f"ollama_chat/{bare}")
    return sorted(out)


def fetch_ollama_tags(base_url: str = DEFAULT_BASE_URL, timeout: float = 5.0) -> dict:
    """GET ``<base_url>/api/tags`` and return the parsed JSON (``{}`` on failure).

    Never raises — a down or absent Ollama server yields an empty payload, which
    :func:`chat_models` turns into an empty list, so callers degrade gracefully.
    """
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return {}


def discover_chat_models(base_url: str = DEFAULT_BASE_URL) -> list[str]:
    """Convenience: fetch tags and return the chat-capable ``ollama_chat/`` ids."""
    return chat_models(fetch_ollama_tags(base_url))
