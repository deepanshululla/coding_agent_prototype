Status: not started

# Phase 13.1 — Project Instructions (AGENTS.md)

## Goal

Add `src/project_instructions.py` to discover `AGENTS.md` / `CLAUDE.md` by walking from `cwd` to the git root, then wire the result into `main.py` via `build_system_prompt(extra=...)` so every session starts briefed on repo conventions automatically.

## Files changed

| File | Change |
|---|---|
| `src/project_instructions.py` | New module — `_git_root`, `_candidate_dirs`, `load_project_instructions(cwd)` |
| `main.py` | Import and call `load_project_instructions(cwd)`; pass result as `extra` to `build_system_prompt` |
| `tests/test_project_instructions.py` | New tests — file discovery, upward walk, symlink dedup, env-var override, empty return when no file |

## Order of operations

1. Write a failing test that calls `load_project_instructions(cwd)` with a temp dir containing an `AGENTS.md` and asserts its content appears in the returned string. Confirm the test fails with `ImportError` or `AttributeError`.
2. Create `src/project_instructions.py` with `_git_root`, `_candidate_dirs`, and `load_project_instructions`. Run the test — it should pass.
3. Add a test for the upward-walk: place `AGENTS.md` one level above `cwd` (still within a fake git root) and assert it is discovered.
4. Add a test for symlink deduplication: symlink `CLAUDE.md` → `AGENTS.md` and assert the content is included only once.
5. Add a test for `AGENT_INSTRUCTIONS_FILES=""` returning `""`.
6. Update `main.py` to import `load_project_instructions` and pass its output as `extra`. Run `uv run pytest -q` — the full suite must be green.

## Verification

- [ ] Tests added: `tests/test_project_instructions.py`
- [ ] Full suite: `uv run pytest -q` — all Phase 12 tests still pass
- [ ] Run command: `uv run main.py "what are the project's test conventions?"` — first model reply references content from `AGENTS.md` without being told
- [ ] Disable loading: `AGENT_INSTRUCTIONS_FILES="" uv run main.py "summarize this codebase"` — no project instructions block in the prompt

### Acceptance (BDD)

```gherkin
Scenario: AGENTS.md rule appears verbatim in the system prompt
  Given an AGENTS.md file exists at the repo root containing the rule
        "Never commit .env files or credentials"
  And the agent is initialized with load_project_instructions(cwd)
  When build_system_prompt is called with extra=load_project_instructions(cwd)
  Then the returned system prompt contains the string
       "Never commit .env files or credentials"
  And the model follows the rule when asked to handle an .env file
```

## Notes / open questions

- Security: `AGENTS.md` from an untrusted repo is injected verbatim into the system prompt — prompt-injection surface. Users should set `AGENT_INSTRUCTIONS_FILES=""` on untrusted repos.
- Both `AGENTS.md` and `CLAUDE.md` are read if both exist; each gets its own `## Project instructions (from <name>)` header.
- `AGENT_INSTRUCTIONS_FILES` env var allows adding `.cursorrules` or other filenames beyond the two defaults.

---

**Tutorial build step 21 of 32** · ← [Phase 12.5 — Logging & Settings](./phase-12-5-logging-and-settings.md) · [Phase 13.2 — Prompt Templates & Hooks](./phase-13-2-prompt-templates-and-hooks.md) →
