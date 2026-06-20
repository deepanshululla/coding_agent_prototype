"""Tests for the system prompt builder."""

import sys
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import config
import memory
import prompts
from types_ import Memory


def test_prompt_contains_cwd(tmp_path):
    result = prompts.build_system_prompt(cwd=str(tmp_path))
    assert str(tmp_path) in result


def test_prompt_contains_today():
    result = prompts.build_system_prompt()
    today = date.today().isoformat()
    assert today in result


def test_prompt_contains_all_tool_names():
    result = prompts.build_system_prompt()
    for name in (
        "read_file",
        "write_file",
        "edit_file",
        "bash",
        "grep",
        "find_files",
        "list_dir",
        "save_memory",
        "list_memories",
    ):
        assert name in result, f"Tool {name!r} missing from system prompt"


def test_prompt_extra_is_appended():
    result = prompts.build_system_prompt(extra="CUSTOM MARKER")
    assert "CUSTOM MARKER" in result


def test_build_system_prompt_loads_memories(tmp_path, monkeypatch):
    """Test that memories are loaded and injected into the system prompt."""
    monkeypatch.setattr(memory, "get_project_memory_dir", lambda cwd=None: tmp_path)
    monkeypatch.setattr(config, "MEMORY_ENABLED", True)

    # Create a test memory
    now = datetime.now(UTC).isoformat()
    mem = Memory(
        name="test-feedback",
        description="User prefers pytest",
        type="feedback",
        content="Always use pytest for tests.\n\n**Why:** Consistency.",
        created=now,
        updated=now,
    )
    memory.save_memory_file(mem, tmp_path)

    # Build system prompt with memories
    prompt = prompts.build_system_prompt(load_memories=True)

    # Verify memory appears in prompt
    assert "test-feedback" in prompt
    assert "User prefers pytest" in prompt
    assert "feedback" in prompt


def test_build_system_prompt_respects_max_load(tmp_path, monkeypatch):
    """Test that only MEMORY_MAX_LOAD memories are included."""
    monkeypatch.setattr(memory, "get_project_memory_dir", lambda cwd=None: tmp_path)
    monkeypatch.setattr(config, "MEMORY_ENABLED", True)
    monkeypatch.setattr(config, "MEMORY_MAX_LOAD", 2)

    # Create 5 memories of different types
    now = datetime.now(UTC).isoformat()
    types_order = ["feedback", "feedback", "user", "project", "reference"]

    for i, mem_type in enumerate(types_order):
        mem = Memory(
            name=f"mem-{i}",
            description=f"Memory {i}",
            type=mem_type,
            content=f"Content {i}",
            created=now,
            updated=now,
        )
        memory.save_memory_file(mem, tmp_path)

    prompt = prompts.build_system_prompt(load_memories=True)

    # Count how many memories appear (should be max 2)
    count = sum(1 for i in range(5) if f"mem-{i}" in prompt)
    assert count <= 2


def test_build_system_prompt_no_memories_when_disabled(tmp_path, monkeypatch):
    """Test that no memory section appears when load_memories=False."""
    monkeypatch.setattr(memory, "get_project_memory_dir", lambda cwd=None: tmp_path)
    monkeypatch.setattr(config, "MEMORY_ENABLED", True)

    # Create a memory
    now = datetime.now(UTC).isoformat()
    mem = Memory(
        name="should-not-appear",
        description="This should not be loaded",
        type="user",
        content="Content",
        created=now,
        updated=now,
    )
    memory.save_memory_file(mem, tmp_path)

    # Build prompt with load_memories=False
    prompt = prompts.build_system_prompt(load_memories=False)

    # Verify memory does NOT appear
    assert "should-not-appear" not in prompt


def test_build_system_prompt_memory_sorting(tmp_path, monkeypatch):
    """Test that memories are sorted by type priority: feedback > user > project > reference."""
    monkeypatch.setattr(memory, "get_project_memory_dir", lambda cwd=None: tmp_path)
    monkeypatch.setattr(config, "MEMORY_ENABLED", True)
    monkeypatch.setattr(config, "MEMORY_MAX_LOAD", 10)

    # Create memories in reverse priority order
    now = datetime.now(UTC).isoformat()
    mems = [
        Memory("memory-ref", "Reference", "reference", "Content", now, now),
        Memory("memory-proj", "Project", "project", "Content", now, now),
        Memory("memory-usr", "User", "user", "Content", now, now),
        Memory("memory-fb", "Feedback", "feedback", "Content", now, now),
    ]

    for mem in mems:
        memory.save_memory_file(mem, tmp_path)

    prompt = prompts.build_system_prompt(load_memories=True)

    # Find positions in prompt (using more unique names to avoid false matches)
    positions = {mem.name: prompt.find(mem.name) for mem in mems if mem.name in prompt}

    # Feedback should appear before user, user before project, project before reference
    if "memory-fb" in positions and "memory-usr" in positions:
        assert positions["memory-fb"] < positions["memory-usr"]
    if "memory-usr" in positions and "memory-proj" in positions:
        assert positions["memory-usr"] < positions["memory-proj"]
    if "memory-proj" in positions and "memory-ref" in positions:
        assert positions["memory-proj"] < positions["memory-ref"]
