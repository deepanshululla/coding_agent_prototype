"""Memory storage, retrieval, and frontmatter parsing.

Memories are stored as markdown files with YAML frontmatter in a project-specific
directory: ~/.agent_memory/<project_hash>/ where project_hash is derived from cwd.
"""

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from config import MEMORY_DIR
from types_ import Memory


def parse_memory_file(path: Path) -> Memory | None:
    """Parse a memory file with frontmatter into a Memory object.

    Returns None if the file cannot be parsed (malformed frontmatter,
    missing required fields, or I/O error). Logs warnings but does not raise.
    """
    try:
        content = path.read_text()
    except Exception:
        return None

    # Match frontmatter between --- delimiters (dotall mode)
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", content, re.DOTALL)
    if not match:
        return None

    frontmatter_text, body = match.groups()

    # Parse frontmatter manually (simple YAML subset: key: value and nested metadata:)
    fields = {}
    metadata = {}
    current_section = fields

    for line in frontmatter_text.split("\n"):
        line = line.strip()
        if not line:
            continue

        if line == "metadata:":
            current_section = metadata
            continue

        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            current_section[key] = value

    # Extract required fields
    name = fields.get("name")
    description = fields.get("description")
    mem_type = metadata.get("type")
    created = metadata.get("created")
    updated = metadata.get("updated")

    # Validate required fields are present
    if not all([name, description, mem_type, created, updated]):
        return None

    # Type narrowing for ty
    assert name is not None
    assert description is not None
    assert mem_type is not None
    assert created is not None
    assert updated is not None

    return Memory(
        name=name,
        description=description,
        type=mem_type,
        content=body.strip(),
        created=created,
        updated=updated,
    )


def save_memory_file(memory: Memory, dir: Path) -> None:
    """Write a memory to disk with frontmatter.

    Auto-updates the 'updated' timestamp to now. Creates the directory if needed.
    """
    dir.mkdir(parents=True, exist_ok=True)

    # Update the timestamp
    memory.updated = datetime.now(UTC).isoformat()

    # Format frontmatter
    frontmatter = f"""---
name: {memory.name}
description: {memory.description}
metadata:
  type: {memory.type}
  created: {memory.created}
  updated: {memory.updated}
---

{memory.content}"""

    file_path = dir / f"{memory.name}.md"
    file_path.write_text(frontmatter)


def load_all_memories(dir: Path) -> list[Memory]:
    """Load all memory files from a directory.

    Skips files that cannot be parsed and returns the successfully parsed memories.
    Returns empty list if the directory doesn't exist.
    """
    if not dir.exists():
        return []

    memories = []
    for file_path in dir.glob("*.md"):
        mem = parse_memory_file(file_path)
        if mem is not None:
            memories.append(mem)

    return memories


def get_project_memory_dir(cwd: str | None = None) -> Path:
    """Get the project-specific memory directory based on cwd hash.

    Uses hashlib.sha256 to hash the cwd to a stable 16-char directory name.
    Creates the directory if it doesn't exist.
    """
    if cwd is None:
        cwd = str(Path.cwd())

    # Hash cwd to stable directory name
    project_hash = hashlib.sha256(cwd.encode()).hexdigest()[:16]
    mem_dir = MEMORY_DIR / project_hash

    # Create if missing
    mem_dir.mkdir(parents=True, exist_ok=True)

    return mem_dir
