Status: not started

# Phase 13.4 — Agent Skills (Install & Read)

## Goal

Implement spec-compliant discovery of `SKILL.md` folders (the open Agent Skills standard), insert a cheap skills menu into the system prompt, and add a `load_skill` tool so the model pulls a skill's full body on demand.

## Files changed

| File | Change |
|---|---|
| `src/skills.py` | Add `Skill` dataclass, `_parse_skill`, `installed_skill_roots`, `discover_skills`, `skills_menu`; add YAML frontmatter parsing and validation |
| `src/tools.py` | Add `load_skill(name)` async function and its schema entry in `TOOLS_SCHEMA`; register in `TOOL_REGISTRY` |
| `src/prompts.py` | Import `skills_menu`; inject `menu = skills_menu()` between tool list and guidelines sections |
| `.claude/skills/changelog/SKILL.md` | New example skill file for end-to-end testing |
| `tests/test_agent_skills.py` | New tests — valid SKILL.md parsed correctly; invalid name/description rejected; `discover_skills` finds `.claude/skills/`; `skills_menu` lists discovered skills; `load_skill` returns body; unknown name returns error string |

## Order of operations

1. Write a failing test: `_parse_skill(path_to_valid_skill_md)` returns a `Skill` with correct `name` and `description`. Confirm `ImportError`.
2. Add `Skill` dataclass and `_parse_skill` to `src/skills.py` (requires `pyyaml` dependency — add to `pyproject.toml`). Run test — green.
3. Write tests for rejection cases: missing `---` frontmatter, name not matching parent dir name, name > 64 chars, description empty or > 1024 chars. Run tests.
4. Add `installed_skill_roots`, `discover_skills`, and `skills_menu` to `src/skills.py`. Write and run tests for discovery from `.claude/skills/` and for `AGENT_CLAUDE_SKILLS=1` including `~/.claude/skills/`.
5. Create `.claude/skills/changelog/SKILL.md` as the test fixture. Write a test that `discover_skills()` returns it and `skills_menu()` contains `"changelog:"`.
6. Add `load_skill` to `src/tools.py` with schema and registry entry. Write a test that calling `load_skill("changelog")` returns the body text; `load_skill("nonexistent")` returns an error string.
7. Update `src/prompts.py` to inject `skills_menu()`. Run `uv run pytest -q`.

## Verification

- [ ] Tests added: `tests/test_agent_skills.py`
- [ ] Full suite: `uv run pytest -q` — `load_skill` follows the "never raise, return error string" contract so existing tool-dispatch tests are unaffected
- [ ] Menu visible: run agent and inspect the printed system prompt or add a debug print — skills menu section present
- [ ] End-to-end: `uv run main.py "generate a changelog entry for this week's commits"` — model sees menu, calls `load_skill("changelog")`, follows instructions
- [ ] Claude skills: `AGENT_CLAUDE_SKILLS=1 uv run main.py "make a mermaid diagram of the agent loop"` — personal skills discovered if `~/.claude/skills/` exists

### Acceptance (BDD)

```gherkin
Scenario: Installed SKILL.md is discovered, advertised, and loaded on demand
  Given a valid SKILL.md exists at .claude/skills/changelog/SKILL.md
  And the agent is initialized with skills_menu() in the system prompt
  When the system prompt is inspected
  Then it contains "changelog: Generate a CHANGELOG entry in Keep-a-Changelog format"
  When the model calls load_skill with name="changelog"
  Then the tool returns the skill body containing "git log --oneline"
  And the model subsequently follows the changelog generation instructions
```

## Notes / open questions

- `pyyaml` must be added as a runtime dependency in `pyproject.toml` (not just a dev dependency).
- `discover_skills` uses `setdefault` so earlier (higher-precedence) roots win on name collision — project `.claude/skills/` beats `~/.claude/skills/`.
- Skills from disabled plugins must be excluded; `_enabled_plugins()` reads `~/.claude/settings.json`. If that file is absent, returns empty set (all plugin skills skipped).
- Menu cost: ~20–50 tokens per skill line, safe to keep permanently in the system prompt even with 30 skills.
- `load_skill` rescans `discover_skills()` on every call — acceptable for the tutorial; could cache if startup latency matters.

---

**Tutorial build step 24 of 32** · ← [Phase 13.3 — Skills](./phase-13-3-skills.md) · [Phase 13.5 — MCP Integration](./phase-13-5-mcp-integration.md) →
