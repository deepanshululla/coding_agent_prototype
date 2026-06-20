Status: not started

# Phase 12.5 — Logging & Settings

## Goal

Route all agent diagnostic events to stderr via loguru (keeping stdout clean for the model's output) and centralise every `AGENT_*` environment variable in a single `src/config.py` reader so other modules import resolved values instead of calling `os.environ` ad hoc.

## Files changed

| File | Change |
|---|---|
| `src/logging_config.py` | New module: `setup_logging()` (idempotent); stderr sink with level from `AGENT_LOG_LEVEL`; optional rotating JSON file sink from `AGENT_LOG_FILE`; exports `logger` and `setup_logging` |
| `src/config.py` | New module: `_int()` and `_csv()` helpers; all `AGENT_*` tunables as module-level constants (`MODEL`, `MAX_TOKENS`, `MAX_ITERATIONS`, `BASH_TIMEOUT`, `BASH_OUTPUT_LIMIT`, `FIND_LIMIT`, `READ_LIMIT`, `BASH_ALLOWLIST`, `PERMISSION_MODE`, `UI`, `THEME`, `MCP_CONFIG`) |
| `src/agent.py` | Import `logger` from `logging_config`; import `MAX_ITERATIONS` from `config`; replace `print(f"  [executing …]")` and `print(f"  [✓ …]")` with `logger.debug`; add `logger.info` for agent start/finish; add `logger.warning` for unknown tool; add `logger.exception` inside `except` blocks |
| `src/provider.py` | Import `MODEL`, `MAX_TOKENS` from `config`; remove module-level constants duplicating these values |
| `src/tools.py` | Import `BASH_TIMEOUT`, `BASH_OUTPUT_LIMIT`, `FIND_LIMIT`, `READ_LIMIT` from `config`; remove local constants |
| `main.py` | Add `from logging_config import setup_logging`; call `setup_logging()` immediately after `load_dotenv()` and before any other src import |
| `tests/test_logging_config.py` | Tests: `setup_logging()` is idempotent; at DEBUG level, tool lifecycle lines appear on stderr; stdout contains no `[executing` or `[✓` markers after migration |
| `tests/test_config.py` | Tests: each tunable reads the env var; `_int` raises `SystemExit` on non-integer input; `_csv` returns the default list when the var is unset |

## Order of operations

1. Create `src/logging_config.py`: remove loguru's default handler, add stderr sink (level from `AGENT_LOG_LEVEL`, default `INFO`), add file sink if `AGENT_LOG_FILE` is set. Export `logger` and `setup_logging`.
2. Create `src/config.py` with all tunables as listed above. Implement `_int` (raises `SystemExit` on bad input) and `_csv` (splits on comma, strips whitespace, returns default when var is unset).
3. Write `tests/test_config.py` — cover the helpers and several representative tunables.
4. Update `src/agent.py`: add imports; replace the two `print` diagnostic calls with `logger.debug`; add `logger.info` at agent start and finish; add `logger.debug` for iteration count; add `logger.warning` for unknown tool; add `logger.exception` inside the tool-call `except` block; replace the `MAX_ITERATIONS` constant with the one from `config`.
5. Update `src/provider.py`: import `MODEL`, `MAX_TOKENS` from `config`; delete the local constants.
6. Update `src/tools.py`: import `BASH_TIMEOUT`, `BASH_OUTPUT_LIMIT`, `FIND_LIMIT`, `READ_LIMIT` from `config`; delete the local constants.
7. Update `main.py`: add `setup_logging()` call immediately after `load_dotenv()`.
8. Write `tests/test_logging_config.py`: capture stderr/stdout in a subprocess or with `capsys`; assert at DEBUG level the expected log lines land on stderr and stdout is clean.
9. Run all tests; run the BDD scenario (red → green); run the four CLI smoke commands.

## Verification

- [ ] Tests added/updated: `tests/test_logging_config.py`, `tests/test_config.py`
- [ ] All tests pass: `uv run pytest tests/test_logging_config.py tests/test_config.py -v`
- [ ] CLI smoke — default INFO: `uv run main.py "list the Python files in src/"` — stderr shows lifecycle `INFO` lines; stdout is model output only
- [ ] CLI smoke — DEBUG level: `AGENT_LOG_LEVEL=DEBUG uv run main.py "list the Python files in src/"` — stderr shows `executing tool bash with` and `tool bash ok:`; stdout has no `[executing` or `[✓`
- [ ] CLI smoke — redirect stdout: `AGENT_LOG_LEVEL=DEBUG uv run main.py "list the Python files in src/" > result.txt` — `result.txt` contains only model text; diagnostics go to terminal
- [ ] CLI smoke — JSON log: `AGENT_LOG_FILE=/tmp/agent.log uv run main.py "run the test suite"` then `jq '.record.message' /tmp/agent.log` shows structured events
- [ ] BDD scenario passes (green):

```gherkin
Scenario: Tool lifecycle events appear on stderr, not stdout, at DEBUG level
  Given the agent with loguru configured via setup_logging()
  And AGENT_LOG_LEVEL=DEBUG is set in the environment
  When the agent processes a task that calls one tool (e.g. read_file)
  Then stderr contains "executing tool read_file with" at DEBUG level
  And stderr contains "tool read_file ok:" at DEBUG level
  And stdout contains only the model's streamed text response
  And stdout does not contain "[executing" or "[✓"
```

## Notes / open questions

- `setup_logging()` must be called before any `from logging_config import logger` in other modules. The only safe call site is the top of `main()` in `main.py`, after `load_dotenv()`. Tests that import `agent.py` directly should call `setup_logging()` in their fixture setup.
- `_int` raises `SystemExit` (not `ValueError`) so a misconfigured env var stops the process immediately with a readable message. This is the "fail closed" posture described in the tutorial tip.
- `BASH_ALLOWLIST` defaults to `[]` (empty list), meaning the allowlist gate from Layer 12.2 reads `AGENT_BASH_ALLOWLIST` directly. `config.py` provides the resolved list for any module that wants to read it without touching `os.environ`; `allowlist._load_allowlist()` can be updated to import from `config` rather than reading the env var itself.
- The `AGENT_LOG_FILE` rotating sink uses `serialize=True` (one JSON object per line) — compatible with `jq` and log aggregators. Rotation is at 10 MB with 5 retained files.
- After this layer, Phase 12 is complete. All five layers compose: allowlist → policy engine → sandboxing → logging/config. Each is independently deployable and testable.

---

**Tutorial build step 20 of 32** · ← [Phase 12.4 — Sandboxing](./phase-12-4-sandboxing.md) · [Phase 13.1 — Project Instructions (AGENTS.md)](./phase-13-1-project-instructions.md) →
