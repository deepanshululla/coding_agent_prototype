from __future__ import annotations

import asyncio
from pathlib import Path


async def read_file(path: str, offset: int = 0, limit: int = 2000) -> str:
    """Read a file, optionally a window of limit lines starting at offset.

    Blocking file I/O is wrapped in asyncio.to_thread so the event loop is not
    stalled — important once tools run in parallel. On failure this returns an
    error *string* rather than raising, so the model can read the error and try
    a corrective action.
    """

    def _read() -> str:
        try:
            lines = Path(path).read_text().splitlines()
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except IsADirectoryError:
            return f"Error: {path} is a directory, not a file"
        except Exception as e:
            return f"Error reading {path}: {e}"
        window = lines[offset : offset + limit]
        return "\n".join(window)

    return await asyncio.to_thread(_read)


TOOLS_SCHEMA: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file. Use offset/limit for large files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to read",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Line to start from (0-indexed)",
                        "default": 0,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max lines to return",
                        "default": 2000,
                    },
                },
                "required": ["path"],
            },
        },
    },
]

TOOL_REGISTRY: dict[str, object] = {
    "read_file": read_file,
}
