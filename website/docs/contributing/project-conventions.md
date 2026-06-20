---
sidebar_position: 2
title: Project Conventions
description: File layout, naming rules, schema format, error handling, and where to put what.
---

# Project Conventions

These are the stable, agreed-upon rules for this codebase. They exist because LiteLLM, async Python, and the OpenAI message format each carry subtle requirements that bite you if you ignore them.

---

## File layout

```
coding_agent_from_scratch/
├── src/
│   ├── agent.py        # The while-loop: outer + inner, streaming, tool dispatch
│   ├── tools.py        # 7 tool schemas + async implementations + TOOL_REGISTRY
│   ├── prompts.py      # build_system_prompt() — dynamic: CWD, date
│   ├── provider.py     # LiteLLM wrapper: one async stream_response() function
│   └── types_.py       # ToolCall, ToolResult dataclasses
├── tests/
│   ├── test_tools.py   # Unit tests for each tool function
│   └── test_agent.py   # Integration tests with a mocked provider
├── docs/
│   └── architecture.md # How the loop works; how to add a tool
├── main.py             # CLI entrypoint — asyncio.run(run_agent(task))
├── plans/              # Per-task implementation plans (YYYY-MM-DD-slug.md)
├── learnings.md        # Non-obvious technical discoveries, newest first
├── CLAUDE.md           # Stable conventions — loaded on every agent session
└── pyproject.toml
```

**Why this layout?**

- `src/` keeps importable code separate from the CLI entrypoint and configuration. It mirrors pi.dev's `packages/` structure without requiring a monorepo.
- `tests/` holds unit tests for pure-function tools and integration tests for the loop. Tools are designed to be testable without a live LLM.
- `docs/` is intentionally minimal. One architecture doc is enough at this stage.

**`src/` is not a package.** There is no `__init__.py`. To make imports work, `pyproject.toml` sets `pythonpath = ["src"]` under `[tool.pytest.ini_options]`, and `main.py` appends `src/` to `sys.path` at startup. Do not add `__init__.py` — it is intentionally absent.

---

## Why `types_` not `types`

Python's standard library has a module named `types`. Naming our file `types.py` would shadow it across the entire process, causing import errors in stdlib code that does `import types`. The trailing underscore is the conventional fix:

```
src/types_.py     # correct
src/types.py      # breaks stdlib — do not use
```

This is the same pattern Python uses for builtins (`list_`, `id_`, `type_` in some libraries). One character prevents a subtle, hard-to-diagnose bug.

---

## OpenAI-style tool schemas, not Anthropic-style

LiteLLM normalizes all providers to OpenAI's format. You write schemas once in OpenAI format; LiteLLM translates them to whatever the underlying provider (Anthropic, Google, OpenAI) needs.

**Correct (OpenAI format, what LiteLLM expects):**

```python
{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read the contents of a file.",
        "parameters": {           # key is "parameters"
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
            },
            "required": ["path"],
        },
    },
}
```

**Incorrect (Anthropic raw SDK format — do not use):**

```python
{
    "name": "read_file",
    "description": "Read the contents of a file.",
    "input_schema": {             # wrong key for LiteLLM
        "type": "object",
        ...
    },
}
```

If you pass Anthropic-style schemas to `litellm.acompletion`, LiteLLM will reject or mishandle them. Always use the `type: "function"` wrapper and `parameters` key.

---

## Tools never raise exceptions

Tool functions must return a descriptive error string and set `is_error=True`. They must never raise a Python exception.

**Correct:**

```python
async def read_file(path: str, offset: int = 0, limit: int = 2000) -> str:
    try:
        lines = Path(path).read_text().splitlines()
        return "\n".join(lines[offset : offset + limit])
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except PermissionError:
        return f"Error: permission denied: {path}"
```

**Why:** If a tool raises, the agent loop crashes. If it returns an error string, the model reads it, reasons about what went wrong, and tries a different approach. That's the intended behavior. Exceptions rob the model of the chance to recover.

The `is_error=True` flag on `ToolResult` is informational — it lets the loop log or surface errors differently — but it does not change how the error string is added to the message history.

---

## Async everywhere

All tool functions are declared `async def`. All blocking I/O (file reads, subprocess calls) is wrapped with `await asyncio.to_thread(...)` so the event loop is not blocked during parallel tool execution.

```python
async def bash(cmd: str, timeout: int = 30) -> str:
    def _run():
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        output = result.stdout + result.stderr
        return output[:10_000]  # truncate to 10k chars
    return await asyncio.to_thread(_run)
```

**Why async?** `litellm.acompletion` is non-blocking. Using `asyncio.gather` for parallel tool execution only works if tool functions are themselves async. A sync `subprocess.run` inside a plain `def` blocks the entire event loop for its duration, defeating parallelism.

The provider layer (`stream_response`) is also async for the same reason: waiting for tokens from the API should not block the event loop.

---

## Where to put what

| Information type | Location | Visibility |
|-----------------|----------|------------|
| Stable conventions (TDD, plan-first, naming rules) | `CLAUDE.md` / `AGENTS.md` | Committed; loaded by every agent session automatically |
| Non-obvious technical discoveries about this codebase | `learnings.md` | Committed; any contributor can read it |
| Multi-session implementation plans | `plans/YYYY-MM-DD-slug.md` | Committed; ephemeral per task |
| Per-user preferences and communication style | Agent auto-memory | Private to that user; not committed |
| Architecture explanation for readers of the code | `docs/architecture.md` | Committed; narrative prose |

**Tiebreaker for `learnings.md` vs `CLAUDE.md`:** if you find yourself writing the same `learnings.md` entry twice across different sessions, the lesson has graduated into a convention — promote it to `CLAUDE.md` and shorten or remove the `learnings.md` entry.

**Do not put secrets in any committed file.** `.env` is gitignored. API keys go there, not in `learnings.md`, not in plan files.

---

## Related pages

- [Development Workflow](./development-workflow.md) — TDD loop, build order, local commands
- [Tools schema format](../tools/schema-format.md) — full schema reference for all 7 tools
- [Architecture overview](../architecture/overview.md) — how the modules wire together
