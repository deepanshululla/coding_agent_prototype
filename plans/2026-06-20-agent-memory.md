Status: not started

# Agent Memory System

## Goal

Add persistent memory capabilities to the agent that allow it to remember information across conversations (sessions), stored as markdown files with frontmatter in a project-specific memory directory. The system will support loading relevant memories into the system prompt and saving new memories via a `save_memory` tool.

## Files changed

| File | Change |
|---|---|
| `src/memory.py` | New module: memory storage, retrieval, and frontmatter parsing |
| `src/types_.py` | Add `Memory` dataclass for representing memory entries |
| `src/tools.py` | Add `save_memory` and `list_memories` tool implementations + schemas in `TOOLS_SCHEMA`, register in `TOOL_REGISTRY` |
| `src/prompts.py` | Extend `build_system_prompt` to load and inject relevant memories via new `load_memories` param |
| `src/config.py` | Add `MEMORY_DIR`, `MEMORY_ENABLED`, and `MEMORY_MAX_LOAD` config vars (follow existing `_bool`, `_int`, `_csv` pattern) |
| `tests/test_memory.py` | New test file: test memory CRUD, frontmatter parsing, retrieval |
| `tests/test_tools.py` | Add tests for save_memory and list_memories tools |
| `tests/test_prompts.py` | Test that memories appear in system prompt when `load_memories=True` |

## Memory File Structure

Memories will be stored in `~/.agent_memory/<project_hash>/` where project_hash is derived from the current working directory. Each memory is a markdown file:

```markdown
---
name: user-preference-testing
description: User prefers pytest over unittest for all new tests
metadata:
  type: feedback
  created: 2026-06-20T15:45:00Z
  updated: 2026-06-20T15:45:00Z
---

User explicitly requested using pytest for all test files. Avoid unittest.mock
patterns and use pytest fixtures instead.

**Why:** Consistency with existing test suite in tests/ directory.
**How to apply:** When writing new tests, use pytest conventions.
```

### Memory types
- `user`: Information about the user (role, preferences, context)
- `feedback`: Corrections and validated approaches  
- `project`: Ongoing work, goals, initiatives
- `reference`: Pointers to external resources

## Integration points

The memory system plugs into the agent at two points:

1. **System prompt** — `agent.py:246` calls `build_system_prompt()` without args. The extended version will auto-load memories when `MEMORY_ENABLED=True` (no call-site change needed).

2. **Tool registry** — `save_memory` and `list_memories` join the existing 8 tools in `tools.TOOL_REGISTRY`. The agent loop in `agent.py` and SDK in `sdk.py` don't need changes; they dispatch any tool in the registry.

No changes needed to:
- `architecture.py` or `src/architectures/*` (they use the system prompt passed via `RunContext`)
- `sdk.py` (dispatches tools generically)
- Main CLI entry point (already calls `build_system_prompt()` via `run_agent`)

## Order of operations

1. **Add Memory dataclass** to `src/types_.py`:
   ```python
   @dataclass
   class Memory:
       name: str              # kebab-case slug
       description: str       # one-line summary
       type: str              # user | feedback | project | reference
       content: str           # markdown body
       created: str           # ISO timestamp
       updated: str           # ISO timestamp
   ```
   - Import datetime if needed for timestamp generation
   - Follow existing pattern (see `ToolResult` dataclass)

2. **Create `src/memory.py`** with:
   - `parse_memory_file(path: Path) -> Memory | None` — parse frontmatter + content
     - Frontmatter format: YAML-like between `---` delimiters (manual parsing, no dependencies)
     - Extract `name`, `description`, `metadata.type`, `metadata.created`, `metadata.updated`
     - Content is everything after closing `---`
     - Return `None` on parse failure (log warning, don't raise)
   - `save_memory_file(memory: Memory, dir: Path) -> None` — write to disk with frontmatter
     - Auto-update `metadata.updated` timestamp
     - Set `metadata.created` only if not already present
     - Format: `---\nname: {name}\ndescription: {description}\nmetadata:\n  type: {type}\n  ...\n---\n\n{content}`
   - `load_all_memories(dir: Path) -> list[Memory]` — scan dir, parse all .md files
     - Silently skip unparseable files (return partial list)
   - `get_project_memory_dir(cwd: str | None = None) -> Path` — hash cwd to stable dir name
     - Use `hashlib.sha256(cwd.encode()).hexdigest()[:16]` for project hash
     - Return `MEMORY_DIR / project_hash`
     - Create directory if it doesn't exist (`mkdir(parents=True, exist_ok=True)`)

3. **Add config vars** to `src/config.py`:
   - `MEMORY_DIR` = `Path.home() / ".agent_memory"` (base directory)
   - `MEMORY_ENABLED` = `_bool("AGENT_MEMORY_ENABLED", True)` (default True)
   - `MEMORY_MAX_LOAD` = `_int("AGENT_MEMORY_MAX_LOAD", 10)` (max memories to inject into prompt)
   - Follow existing pattern: use `_bool()`, `_int()`, `_csv()` helpers defined at top of config.py

4. **Add `save_memory` tool** to `src/tools.py`:
   - Define async function following existing tool pattern (wraps blocking I/O in `asyncio.to_thread`)
   - Parameters: `name` (kebab-case slug), `description` (one-line), `type` (user|feedback|project|reference), `content` (markdown body)
   - Validates inputs (type is valid, name is kebab-case, no duplicate names)
   - Creates/updates memory file in project memory dir using `memory.save_memory_file()`
   - Returns confirmation message (or "Error:" prefix on failure — tools never raise)
   - Add schema to `TOOLS_SCHEMA` list:
     ```python
     {
         "type": "function",
         "function": {
             "name": "save_memory",
             "description": "Save a memory to the project memory store. Use kebab-case names.",
             "parameters": {
                 "type": "object",
                 "properties": {
                     "name": {"type": "string", "description": "Kebab-case slug (e.g., 'user-prefers-pytest')"},
                     "description": {"type": "string", "description": "One-line summary"},
                     "type": {"type": "string", "enum": ["user", "feedback", "project", "reference"]},
                     "content": {"type": "string", "description": "Markdown content body"},
                 },
                 "required": ["name", "description", "type", "content"],
             },
         },
     }
     ```
   - Add to `TOOL_REGISTRY` dict: `"save_memory": save_memory`

5. **Add `list_memories` tool** to `src/tools.py`:
   - Define async function following existing tool pattern
   - No parameters (or optional `type` filter)
   - Loads all memories via `memory.load_all_memories(memory.get_project_memory_dir())`
   - Returns formatted list of all memories (name, type, description)
   - Format: `"- {name} ({type}): {description}"` per line
   - Helps agent discover what's already saved
   - Add schema to `TOOLS_SCHEMA` list:
     ```python
     {
         "type": "function",
         "function": {
             "name": "list_memories",
             "description": "List all saved memories in the project memory store.",
             "parameters": {"type": "object", "properties": {}},
         },
     }
     ```
   - Add to `TOOL_REGISTRY` dict: `"list_memories": list_memories`

6. **Extend `build_system_prompt`** in `src/prompts.py`:
   - Add optional `load_memories: bool = True` parameter to function signature
   - When `load_memories=True` and `MEMORY_ENABLED=True`, load all memories from project dir using `memory.load_all_memories()`
   - Sort by relevance (heuristic: feedback > user > project > reference)
   - Take top `MEMORY_MAX_LOAD` entries
   - Inject into system prompt as a `## Memory` section after `## Environment`, before `{extra}`
   - Format: bullet list with name, type, description + content preview (first 200 chars)
   - Note: `build_system_prompt` is called in `agent.py` and architectures — update call sites if needed

7. **Write tests** in `tests/test_memory.py`:
   - Use `tmp_path` fixture for isolated test memory dirs
   - `test_parse_memory_file_valid()` — valid frontmatter + content
   - `test_parse_memory_file_invalid_frontmatter()` — malformed YAML returns None
   - `test_parse_memory_file_missing_fields()` — missing required fields returns None
   - `test_save_load_roundtrip()` — save Memory, load it back, assert equal
   - `test_get_project_memory_dir_stable()` — same cwd → same hash dir
   - `test_get_project_memory_dir_creates()` — dir is created if missing
   - `test_load_all_memories_empty()` — empty dir returns empty list
   - `test_load_all_memories_multiple()` — loads all .md files, skips non-.md

8. **Write tool tests** in `tests/test_tools.py`:
   - `test_save_memory_creates_file()` — creates .md file with correct frontmatter
   - `test_save_memory_invalid_type()` — returns "Error: invalid type" for bad type
   - `test_save_memory_updates_existing()` — overwrites file, updates timestamp
   - `test_save_memory_kebab_case_validation()` — rejects non-kebab-case names (optional)
   - `test_list_memories_empty()` — returns "No memories saved" or similar
   - `test_list_memories_multiple()` — returns formatted list of all memories
   - Mock `memory.get_project_memory_dir()` to use `tmp_path` for isolation

9. **Write prompt tests** in `tests/test_prompts.py`:
   - `test_build_system_prompt_with_memories()` — create test memories, call with `load_memories=True`, assert memory section appears
   - `test_build_system_prompt_respects_max_load()` — create 15 memories, assert only top 10 appear when `MEMORY_MAX_LOAD=10`
   - `test_build_system_prompt_no_memories_when_disabled()` — call with `load_memories=False`, assert no memory section
   - `test_build_system_prompt_memory_sorting()` — create memories of different types, assert sorted by priority (feedback > user > project > reference)
   - Mock `memory.load_all_memories()` and `memory.get_project_memory_dir()` for isolation
   - Use monkeypatch fixture to set `config.MEMORY_ENABLED` during tests

## Implementation tips

- Start with `Memory` dataclass and `memory.py` module (pure functions, easy to test)
- TDD loop: write failing test, implement minimal code, refactor, repeat
- Use `from datetime import datetime, timezone` for ISO timestamps: `datetime.now(timezone.utc).isoformat()`
- Kebab-case validation regex: `^[a-z0-9]+(?:-[a-z0-9]+)*$`
- Tools import from `memory` module: `from memory import get_project_memory_dir, load_all_memories, save_memory_file`
- Prompts import from `memory` module: `from memory import load_all_memories, get_project_memory_dir`
- Config imports in `memory.py`: `from config import MEMORY_DIR, MEMORY_ENABLED, MEMORY_MAX_LOAD`

## Verification

- [ ] Tests added: `tests/test_memory.py`, `tests/test_tools.py`, `tests/test_prompts.py`
- [ ] All tests pass: `uv run pytest` (run after each implementation step)
- [ ] Type check passes: `uv run mypy src/` (if mypy is configured)
- [ ] Linter passes: `uv run ruff check src/` (follow existing code style)
- [ ] Manual CLI run: `python main.py "save a memory that I prefer pytest over unittest"` creates file in `~/.agent_memory/<hash>/`
- [ ] Manual CLI run: `python main.py "list my memories"` shows saved memory
- [ ] Manual CLI run: `python main.py "what testing framework do I prefer?"` — memory appears in system prompt, agent references it
- [ ] Check file format: `cat ~/.agent_memory/<hash>/<name>.md` — valid frontmatter + content
- [ ] Verify debug output (optional): set `AGENT_LOG_LEVEL=DEBUG` to see memory loading logs

## Notes / design decisions

- **Retrieval strategy:** Initially load all memories up to MEMORY_MAX_LOAD (default 10). Sort by type priority: feedback > user > project > reference. Future: semantic search / embedding-based retrieval when memory count grows large.
  
- **Memory updates:** If agent calls `save_memory` with an existing name, **replace** the file (update `metadata.updated` timestamp). No append mode in v1 — edit the file manually for merges.

- **Cross-project memories:** Project-scoped only in v1. Memory dir is `~/.agent_memory/<sha256(cwd)[:16]>/`. No global memory dir yet (deferred).

- **Memory pruning:** No automatic deletion. User manually deletes `.md` files from `~/.agent_memory/<hash>/`. Future: add `delete_memory` tool.

- **Frontmatter library:** Parse manually — no new dependencies. Simple YAML subset (strings only, one level of nesting for `metadata:`). Regex-based extraction: `^---\n(.*?)\n---\n(.*)$` (dotall mode).

- **Tool visibility:** `save_memory` and `list_memories` are always visible in tool list (low-risk operations). Permission mode doesn't gate them. Follow existing pattern: tools never raise, return `"Error: ..."` strings on failure.

- **Error handling:** Follow existing tool pattern (see `tools.py`):
  - Never raise exceptions from tool functions
  - Return `"Error: ..."` prefix for all failures
  - Wrap blocking I/O in `asyncio.to_thread` to avoid blocking event loop
  - Use `_truncate()` helper if memory content is large (though unlikely for metadata files)

- **Testing strategy:** TDD loop per CLAUDE.md. Write failing tests first for each function in `memory.py`, then implement. Use `tmp_path` fixture from pytest for test isolation.
