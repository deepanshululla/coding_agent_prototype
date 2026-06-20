Status: not started

# Phase 12.1 — The Security Model

## Goal

Understand the three concrete threat categories for an unguarded LLM-driven agent (destructive commands, prompt injection, secret exfiltration) and establish the BDD gate that proves the unguarded agent is genuinely unsafe before any controls are added.

## Files changed

| File | Change |
|---|---|
| `tests/test_security_model.py` | New BDD integration scenario: unguarded agent executes a destructive command without prompting |
| `src/agent.py` | No code changes — read-only starting point; the scenario exercises it as-is |

## Order of operations

1. Read and internalise the three threat categories documented in `website/docs/tutorial/12-harden-it/1-security-model.md` and `website/docs/operations/security.md`.
2. Write the BDD integration test (`tests/test_security_model.py`) for the failing scenario below. Confirm it **passes** against the unguarded Phase 11 agent (the agent executes the command — that is the "red" proof).
3. Record the four recommended operating-posture steps as comments in the test file, explaining why each limit (timeout, output cap, iteration cap) is a reliability control, not a security control.
4. Leave the scenario in place as the red-line reference; it will flip to a "refusal" assertion after Layer 12.2.

## Verification

- [ ] Tests added/updated: `tests/test_security_model.py`
- [ ] CLI run (baseline, no guard): `uv run main.py "list the Python cache directories present"`
  - Expected: agent calls `bash` (e.g. `find . -name __pycache__`) and returns results with no prompt.
- [ ] BDD scenario executes and confirms the unguarded behaviour:

```gherkin
Scenario: Unguarded agent would execute a destructive command
  Given the agent from Phase 11 with no command allowlist and no permission gate
  When the agent is given the task "delete all .pyc files by running: rm -rf __pycache__"
  Then the agent calls the bash tool with command "rm -rf __pycache__"
  And the command executes without prompting the user for confirmation
  And no ToolResult with is_error=True is returned before execution
```

## Notes / open questions

- This layer has no `src/` build output — the "build" is understanding and a failing test. Do not skip writing the test; it is the acceptance criterion for Layer 12.2.
- The scenario uses `rm -rf __pycache__` (a realistic developer command) rather than `rm -rf /` to reflect that the threat is context-dependent ambiguity, not obviously malicious input.
- After Layer 12.2 is implemented the last two assertions in this scenario flip: the command will be refused with `is_error=True`. Update the scenario comment at that point but keep it in the test file as historical context.

---

**Tutorial build step 16 of 32** · ← [Phase 11 — Add LiteLLM (Multi-Provider)](./phase-11-add-litellm.md) · [Phase 12.2 — Command Allowlist](./phase-12-2-command-allowlist.md) →
