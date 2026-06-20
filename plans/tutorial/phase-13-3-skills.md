Status: done
Branch: step/phase-13-3-skills

# Phase 13.3 — Skills

## Goal

Introduce a dict-based skill registry in `src/skills.py` and extend `build_system_prompt` with a `skills` parameter so named instruction blocks are composed into the system prompt per session, controlled by `AGENT_SKILLS` env var or `--skills` CLI flag.

## Files changed

| File | Change |
|---|---|
| `src/skills.py` | New module — `SKILLS` dict, `DEFAULT_SKILLS`, `ACTIVE_SKILLS` (env-driven) |
| `src/prompts.py` | Import `SKILLS` and `ACTIVE_SKILLS`; add `skills: list[str] | None` param to `build_system_prompt`; inject skill blocks between tool list and guidelines |
| `main.py` | Add `argparse` with `--skills` flag; resolve active skills (CLI > env > default); pass to `build_system_prompt` |
| `tests/test_skills.py` | New tests — active skill text present in prompt; deactivated skill text absent; `--skills` override; empty skills list yields bare prompt |

## Order of operations

1. Write a failing test: `build_system_prompt(skills=["tdd"])` should contain "Write a failing test before adding any new code". Confirm import error.
2. Create `src/skills.py` with `SKILLS` dict (tdd, git, explain, security), `DEFAULT_SKILLS`, and `ACTIVE_SKILLS`. Run test — still fails (prompt ignores `skills`).
3. Update `build_system_prompt` in `src/prompts.py` to accept `skills` param and inject matching blocks. Run test — green.
4. Write test: `build_system_prompt(skills=["tdd"])` must NOT contain explain skill text. Run test.
5. Write test: `build_system_prompt(skills=["explain"])` contains explain text and not tdd text. Run test.
6. Write test: `build_system_prompt(skills=[])` contains none of the skill block strings. Run test.
7. Add `argparse` to `main.py` with `--skills` flag; thread `active_skills` into `build_system_prompt`. Run `uv run pytest -q`.

## Verification

- [ ] Tests added: `tests/test_skills.py`
- [ ] Full suite: `uv run pytest -q` — callers that omit `skills` still get `ACTIVE_SKILLS` default, no breakage
- [ ] Default run: `uv run main.py "add a new grep_lines function to tools.py"` — tdd/git blocks present in prompt
- [ ] Env override: `AGENT_SKILLS=security uv run main.py "audit src/agent.py for injection risks"` — only security block present
- [ ] CLI flag: `uv run main.py --skills explain "walk me through how the streaming loop works"` — explain block present
- [ ] No skills: `uv run main.py --skills "summarize this repo in one paragraph"` — no skill blocks

### Acceptance (BDD)

```gherkin
Scenario: Active skill appears in the prompt; deactivated skill does not
  Given AGENT_SKILLS is set to "tdd"
  When build_system_prompt is called with skills=["tdd"]
  Then the returned prompt contains "Write a failing test before adding any new code"
  And the returned prompt does not contain "Walk through code section by section"
  When build_system_prompt is called with skills=["explain"]
  Then the returned prompt contains "Walk through code section by section"
  And the returned prompt does not contain "Write a failing test before adding any new code"
```

## Notes / open questions

- Skill precedence: CLI `--skills` > `AGENT_SKILLS` env var > `DEFAULT_SKILLS`. An empty `--skills` flag activates zero skills.
- Unknown skill names in `skills` list are silently skipped (guarded by `if s in SKILLS`). Consider a warning log.
- `main.py` switches from `sys.argv` slicing to `argparse` in this layer — verify no regression for callers that pass multi-word tasks as positional args.

---

**Tutorial build step 23 of 32** · ← [Phase 13.2 — Prompt Templates & Hooks](./phase-13-2-prompt-templates-and-hooks.md) · [Phase 13.4 — Agent Skills (Install & Read)](./phase-13-4-agent-skills.md) →
