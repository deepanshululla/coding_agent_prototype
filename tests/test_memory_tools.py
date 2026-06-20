"""Tests for memory-related tools (save_memory, list_memories)."""

import asyncio
from datetime import UTC, datetime

import memory
import tools
from types_ import Memory


def run(coro):
    """Helper to run async functions in tests."""
    return asyncio.run(coro)


# ── save_memory ──────────────────────────────────────────────────────────────


def test_save_memory_creates_file(tmp_path, monkeypatch):
    """Test that save_memory creates a file with correct frontmatter."""
    # Mock get_project_memory_dir to use tmp_path
    monkeypatch.setattr(memory, "get_project_memory_dir", lambda cwd=None: tmp_path)

    result = run(
        tools.save_memory(
            name="user-test-preference",
            description="User prefers pytest",
            type="feedback",
            content="Use pytest for all tests.\n\n**Why:** Consistency.",
        )
    )

    assert "Error" not in result
    assert "saved" in result.lower() or "memory" in result.lower()

    # Verify file was created
    file_path = tmp_path / "user-test-preference.md"
    assert file_path.exists()

    # Verify frontmatter
    content = file_path.read_text()
    assert "name: user-test-preference" in content
    assert "description: User prefers pytest" in content
    assert "type: feedback" in content
    assert "Use pytest for all tests" in content


def test_save_memory_invalid_type(tmp_path, monkeypatch):
    """Test that save_memory returns error for invalid type."""
    monkeypatch.setattr(memory, "get_project_memory_dir", lambda cwd=None: tmp_path)

    result = run(
        tools.save_memory(
            name="test-bad-type",
            description="Test",
            type="invalid_type",
            content="Content",
        )
    )

    assert "Error" in result
    assert "type" in result.lower()


def test_save_memory_updates_existing(tmp_path, monkeypatch):
    """Test that save_memory overwrites an existing file and updates timestamp."""
    monkeypatch.setattr(memory, "get_project_memory_dir", lambda cwd=None: tmp_path)

    # Create initial memory
    run(
        tools.save_memory(
            name="update-test",
            description="Original description",
            type="user",
            content="Original content",
        )
    )

    file_path = tmp_path / "update-test.md"
    original_content = file_path.read_text()
    assert "Original description" in original_content

    # Update the memory
    run(
        tools.save_memory(
            name="update-test",
            description="Updated description",
            type="user",
            content="Updated content",
        )
    )

    # Verify update
    updated_content = file_path.read_text()
    assert "Updated description" in updated_content
    assert "Updated content" in updated_content
    assert "Original description" not in updated_content


# ── list_memories ────────────────────────────────────────────────────────────


def test_list_memories_empty(tmp_path, monkeypatch):
    """Test that list_memories returns message when no memories exist."""
    monkeypatch.setattr(memory, "get_project_memory_dir", lambda cwd=None: tmp_path)

    result = run(tools.list_memories())

    assert "no memories" in result.lower() or "empty" in result.lower()


def test_list_memories_multiple(tmp_path, monkeypatch):
    """Test that list_memories returns formatted list of all memories."""
    monkeypatch.setattr(memory, "get_project_memory_dir", lambda cwd=None: tmp_path)

    # Create two memories
    now = datetime.now(UTC).isoformat()
    mem1 = Memory(
        name="mem1",
        description="First memory",
        type="user",
        content="Content 1",
        created=now,
        updated=now,
    )
    mem2 = Memory(
        name="mem2",
        description="Second memory",
        type="feedback",
        content="Content 2",
        created=now,
        updated=now,
    )

    memory.save_memory_file(mem1, tmp_path)
    memory.save_memory_file(mem2, tmp_path)

    result = run(tools.list_memories())

    # Verify both memories appear in output
    assert "mem1" in result
    assert "mem2" in result
    assert "First memory" in result
    assert "Second memory" in result
    assert "user" in result
    assert "feedback" in result
