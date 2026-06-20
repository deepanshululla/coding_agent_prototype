---
sidebar_position: 1
title: Development Workflow
description: TDD loop, plan-first discipline, build order, and local dev commands for contributors.
---

# Development Workflow

This page summarizes how we expect contributions to be made. The practices come from `CLAUDE.md` and the build order comes from `PLAN.md`. If you follow these, your PRs will land faster.

---

## Test-driven development (TDD)

Every new function, class, or module gets a test before it gets code. The loop is three steps:

1. **Write a failing test first.** Place it under `tests/` — `test_tools.py` for tool functions, `test_agent.py` for loop behavior. Run it and confirm it fails for the *right* reason: an assertion failure or a `NotImplementedError`, not an import error or syntax problem.
2. **Write the minimum code to make it pass.** Don't add scope beyond what the test demands. If the test only checks that `read_file` returns an error string for a missing path, don't add caching.
3. **Refactor with the test green.** Rename, deduplicate, extract helpers. Re-run after every change.

Repeat until the feature is complete.

**What TDD applies to:** new tools, new agent behaviors, new utilities, changes to `types_.py` dataclasses.

**What it doesn't apply to:** prose changes, comment edits, `PLAN.md` updates, one-off scripts you explicitly mark throwaway.

**If TDD genuinely doesn't fit** (e.g., you're exploring a new LiteLLM API surface for the first time): say so in the PR description and commit a backfill test once the shape is known. Don't silently skip.

---

## Plan first for non-trivial changes

Any change that touches three or more files, introduces a new abstraction, or makes an architectural decision needs a stated plan before code is written.

One paragraph is enough: what changes, where, in what order, what gets tested. For a solo contributor working in a conversation context, state the plan in the conversation. For longer-lived work, write it to a file:

```
plans/YYYY-MM-DD-<kebab-slug>.md
```

**Filename rules:**
- Date = when the plan was written, not when work completes.
- Slug = 2–6 words, lowercase, hyphenated. Example: `2026-06-19-add-grep-tool.md`.
- Do not add suffixes like `-plan` or `-design`.

**File contents:**
```markdown
Status: not started   # update to: in progress | done | abandoned

Goal: <one sentence>

## Changes
| File | What changes |
|------|--------------|
| src/tools.py | add grep implementation |
| tests/test_tools.py | add test_grep_* suite |

## Order
1. test first (test_grep_returns_matches)
2. implement grep()
3. add to TOOL_REGISTRY and TOOLS_SCHEMA
```

**Before starting any non-trivial work:** run `ls plans/` first. A prior plan may already cover what you're about to redo.

**If the plan goes sideways mid-implementation** (the abstraction doesn't fit, a test reveals a wrong mental model): stop and re-plan. Don't push through with a worse version of the original.

---

## Verify before declaring done

Never report a task complete on intent alone. Prove it:

| Change type | Proof |
|-------------|-------|
| New code path | Run the test that exercises it and paste the passing output |
| CLI change | Run `uv run main.py "<task>"` and read the output |
| Tool implementation | `uv run pytest tests/test_tools.py -v` |
| Full agent loop | `uv run pytest tests/test_agent.py -v` |

"It should work" is not verification. "I ran X and got Y" is.

---

## Root cause over patch

When a test fails or an unexpected behavior appears: find *why* before fixing. A patch that catches and ignores, hard-codes around a flaky boundary, or marks a test `skip` is a debt note, not a fix.

If root-causing costs more than the current situation warrants, surface that tradeoff explicitly. Don't ship a silent workaround.

---

## Build order

The modules form a dependency chain. Follow this order: each step has no imports from a later step.

| Step | File | Depends on | First milestone |
|------|------|-----------|-----------------|
| 1 | `src/types_.py` | stdlib only | `ToolCall` and `ToolResult` dataclasses exist |
| 2 | `src/tools.py` + `tests/test_tools.py` | `types_.py`, stdlib | Each tool passes its unit tests independently of any LLM |
| 3 | `src/prompts.py` | stdlib only | `build_system_prompt()` returns a string with CWD + date |
| 4 | `src/provider.py` | `tools.py`, litellm | `stream_response()` yields OpenAI-format chunks for a hardcoded message |
| 5 | `src/agent.py` | `provider.py`, `tools.py`, `prompts.py`, `types_.py` | Loop runs end-to-end; a single tool call round-trip works |
| 6 | `main.py` | `agent.py` | `uv run main.py "list .py files"` produces tool output to stdout |
| 7 | `docs/architecture.md` | — | Fill in after the loop works; explains the event flow |
| 8 | `tests/test_agent.py` | `agent.py`, mock of `provider.py` | Loop logic is tested with canned stream chunks, no real LLM |

At each step, run something and read the output before moving to the next step.

---

## Local dev commands

```bash
# Install dependencies
uv add litellm python-dotenv

# Run the agent on a task
uv run main.py "add type hints to all functions in tools.py"

# Run all tests
uv run pytest

# Run tool unit tests only
uv run pytest tests/test_tools.py -v

# Run agent integration tests only
uv run pytest tests/test_agent.py -v

# Run a single test by name
uv run pytest tests/test_tools.py::test_read_file_missing_path -v
```

:::note
`src/` is not a package (no `__init__.py`). Pytest finds it via `pythonpath = ["src"]` in `pyproject.toml` under `[tool.pytest.ini_options]`. `main.py` adds `src/` to `sys.path` at startup. Do not add an `__init__.py` — it is intentionally absent.
:::

---

## Related pages

- [Project Conventions](./project-conventions.md) — file layout, naming rules, schema format
- [Architecture overview](../architecture/overview.md) — the loop design and module responsibilities
- [Tools overview](../tools/overview.md) — the 7 tools and how to add a new one
