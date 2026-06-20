"""Tests for the memory system."""

from datetime import UTC, datetime

import memory
from types_ import Memory


def test_memory_dataclass_creation():
    """Test that Memory dataclass can be created with all fields."""
    now = datetime.now(UTC).isoformat()
    mem = Memory(
        name="test-memory",
        description="A test memory",
        type="feedback",
        content="This is test content.",
        created=now,
        updated=now,
    )

    assert mem.name == "test-memory"
    assert mem.description == "A test memory"
    assert mem.type == "feedback"
    assert mem.content == "This is test content."
    assert mem.created == now
    assert mem.updated == now


# ── parse_memory_file ──────────────────────────────────────────────────────


def test_parse_memory_file_valid(tmp_path):
    """Test parsing a valid memory file with frontmatter."""
    content = """---
name: user-prefers-pytest
description: User prefers pytest over unittest
metadata:
  type: feedback
  created: 2026-06-20T10:00:00Z
  updated: 2026-06-20T10:00:00Z
---

User explicitly requested pytest for all tests.

**Why:** Consistency with existing tests.
**How to apply:** Use pytest conventions."""

    file_path = tmp_path / "user-prefers-pytest.md"
    file_path.write_text(content)

    mem = memory.parse_memory_file(file_path)

    assert mem is not None
    assert mem.name == "user-prefers-pytest"
    assert mem.description == "User prefers pytest over unittest"
    assert mem.type == "feedback"
    assert mem.created == "2026-06-20T10:00:00Z"
    assert mem.updated == "2026-06-20T10:00:00Z"
    assert "User explicitly requested" in mem.content
    assert "**Why:**" in mem.content


def test_parse_memory_file_invalid_frontmatter(tmp_path):
    """Test that malformed frontmatter returns None."""
    content = """---
name: broken
no closing delimiter
content here"""

    file_path = tmp_path / "broken.md"
    file_path.write_text(content)

    mem = memory.parse_memory_file(file_path)
    assert mem is None


def test_parse_memory_file_missing_fields(tmp_path):
    """Test that missing required fields returns None."""
    content = """---
name: incomplete
description: Missing metadata
---

Content here."""

    file_path = tmp_path / "incomplete.md"
    file_path.write_text(content)

    mem = memory.parse_memory_file(file_path)
    assert mem is None


# ── save_memory_file and load roundtrip ────────────────────────────────────


def test_save_load_roundtrip(tmp_path):
    """Test saving and loading a memory preserves all data."""
    now = datetime.now(UTC).isoformat()
    original = Memory(
        name="roundtrip-test",
        description="Test memory for roundtrip",
        type="user",
        content="Test content with\nmultiple lines.",
        created=now,
        updated=now,
    )

    memory.save_memory_file(original, tmp_path)

    loaded = memory.parse_memory_file(tmp_path / "roundtrip-test.md")

    assert loaded is not None
    assert loaded.name == original.name
    assert loaded.description == original.description
    assert loaded.type == original.type
    assert loaded.content.strip() == original.content.strip()
    assert loaded.created == original.created
    assert loaded.updated == original.updated


# ── get_project_memory_dir ─────────────────────────────────────────────────


def test_get_project_memory_dir_stable(tmp_path):
    """Test that same cwd produces same hash directory."""
    cwd = "/some/project/path"
    dir1 = memory.get_project_memory_dir(cwd)
    dir2 = memory.get_project_memory_dir(cwd)

    assert dir1 == dir2
    assert len(dir1.name) == 16  # 16-char hash


def test_get_project_memory_dir_creates(tmp_path, monkeypatch):
    """Test that the memory directory is created if missing."""
    # Mock MEMORY_DIR to use tmp_path
    import config

    monkeypatch.setattr(config, "MEMORY_DIR", tmp_path)

    cwd = "/test/project"
    mem_dir = memory.get_project_memory_dir(cwd)

    assert mem_dir.exists()
    assert mem_dir.is_dir()


# ── load_all_memories ──────────────────────────────────────────────────────


def test_load_all_memories_empty(tmp_path):
    """Test that empty directory returns empty list."""
    memories = memory.load_all_memories(tmp_path)
    assert memories == []


def test_load_all_memories_multiple(tmp_path):
    """Test loading multiple memory files."""
    # Create two valid memories
    mem1 = Memory(
        name="mem1",
        description="First memory",
        type="user",
        content="Content 1",
        created="2026-06-20T10:00:00Z",
        updated="2026-06-20T10:00:00Z",
    )
    mem2 = Memory(
        name="mem2",
        description="Second memory",
        type="feedback",
        content="Content 2",
        created="2026-06-20T11:00:00Z",
        updated="2026-06-20T11:00:00Z",
    )

    memory.save_memory_file(mem1, tmp_path)
    memory.save_memory_file(mem2, tmp_path)

    # Add a non-.md file that should be skipped
    (tmp_path / "readme.txt").write_text("Not a memory")

    memories = memory.load_all_memories(tmp_path)

    assert len(memories) == 2
    names = {m.name for m in memories}
    assert "mem1" in names
    assert "mem2" in names
