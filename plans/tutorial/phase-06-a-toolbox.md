Status: done
Branch: step/phase-06-a-toolbox

# Phase 6 — A Toolbox

## Goal

Expand `src/tools.py` from a single `read_file` to the full seven-tool implementation behind a shared registry, and enforce the cardinal contract that every tool returns a descriptive error string on failure rather than raising a Python exception.

## Files changed

| File | Change |
|---|---|
| `src/tools.py` | Replace single-tool stub with all seven async tool functions (`read_file`, `write_file`, `edit_file`, `bash`, `grep`, `find_files`, `list_dir`), module-level caps (`BASH_TIMEOUT`, `BASH_OUTPUT_LIMIT`, `FIND_LIMIT`), `_truncate` helper, full `TOOLS_SCHEMA` list, and updated `TOOL_REGISTRY` dict |
| `tests/test_tools.py` | Add 10 new tests covering all tools and the structural registry/schema invariant |

## Order of operations

1. Write the failing tests in `tests/test_tools.py` (all 10 listed in the tutorial) and confirm they fail with import/attribute errors, not framework errors.
2. Add the module-level constants (`BASH_TIMEOUT`, `BASH_OUTPUT_LIMIT`, `FIND_LIMIT`) and the `_truncate` helper to `src/tools.py`.
3. Implement `write_file`, `edit_file`, `bash`, `grep`, `find_files`, and `list_dir` as async functions with `asyncio.to_thread`-wrapped blocking inner functions, each following the never-raise contract.
4. Extend `TOOLS_SCHEMA` with entries for all six new tools (keeping the existing `read_file` entry).
5. Add all six new callables to `TOOL_REGISTRY`.
6. Run `uv run pytest tests/test_tools.py -v` and confirm all 10 tests pass.

## Verification

- [ ] Tests added/updated: `tests/test_tools.py` (10 tests pass)
- [ ] CLI / service run: `uv run main.py "List the files in the src/ directory, then write a file called /tmp/hello.txt containing the word hello"`
- [ ] Verify write side-effect: `cat /tmp/hello.txt` outputs `hello`
- [ ] BDD acceptance criteria (run before/after the build as a red/green gate):

```gherkin
Feature: The toolbox and the never-raise contract
  Every tool returns a string on success or failure — it never raises.
  The registry and schema stay in sync at exactly 7 entries.

  Scenario: a missing-file read returns an error string and the loop continues
    Given a scripted model that calls read_file on "/no/such/file.txt"
    And the scripted model will then return a plain-text final answer
    When run_agent runs
    Then the tool result message for "read_file" contains "Error"
    And the tool result message is role "tool", not a Python exception
    And the model receives a second turn and produces a final answer

  Scenario: edit_file refuses a non-unique old_string with an error result
    Given a file "dup.py" whose content contains the line "x = 1" twice
    And a scripted model that calls edit_file with old_string "x = 1" on that file
    And the scripted model will then return a plain-text final answer
    When run_agent runs
    Then the tool result message for "edit_file" contains "unique"
    And the tool result message for "edit_file" contains "Error"
    And the file "dup.py" is unchanged (no edit was applied)

  Scenario: bash output over the cap is truncated but still returned with the exit code
    Given a scripted model that calls bash with a command that produces more than 10000 chars of output
    And the scripted model will then return a plain-text final answer
    When run_agent runs
    Then the tool result message for "bash" contains "truncated"
    And the tool result message for "bash" contains "exit code"
    And the tool result message for "bash" is a non-empty string (not a Python exception)

  Scenario: the registry and TOOLS_SCHEMA expose exactly the 7 tools
    Given the tools module is imported
    When the TOOL_REGISTRY and TOOLS_SCHEMA are inspected
    Then TOOL_REGISTRY contains exactly the keys "read_file", "write_file", "edit_file", "bash", "grep", "find_files", "list_dir"
    And TOOLS_SCHEMA contains exactly 7 entries
    And every name in TOOLS_SCHEMA matches a key in TOOL_REGISTRY
```

## Notes / open questions

- The `edit_file` uniqueness check is critical: a silent double-replace would corrupt two locations without the model knowing. The count check turns this into a recoverable error.
- Every blocking inner function (`_read`, `_write`, `_edit`, `_run`, `_grep`, `_find`, `_list`) must be wrapped in `asyncio.to_thread` — this is what lets Phase 7's `asyncio.gather` parallelize them.
- The `test_registry_matches_schema` structural test acts as a lint rule: if you add a tool function but forget to add its schema entry (or vice versa), it fails immediately.

---

**Tutorial build step 6 of 32** · ← [Phase 5 — Streaming Tool Calls](./phase-05-streaming-tool-calls.md) · [Phase 7 — Parallel Tool Execution](./phase-07-parallel-tools.md) →
