Status: not started

# Phase 15 — Steering

## Goal

Enable mid-session redirects by replacing the unconditional `break` at the end of `run_agent`'s outer loop with a check against `pending_messages`, and expose an injected `get_steering_messages` async callable so callers (stdin reader, asyncio.Queue, SDK `steer()`) can feed follow-up tasks without re-running prior tool calls.

## Files changed

| File | Change |
|---|---|
| `src/agent.py` | Replace outer-loop `break` with `get_steering_messages` callback poll; extend `run_agent` signature with optional `get_steering_messages=None`; add `pending_messages` flush at start of inner loop if not already present |
| `tests/test_steering.py` | New file — BDD integration scenario: mock two stream phases (first ends with `finish_reason="stop"`, second ends with a `bash` tool call); supply a `get_steering_messages` that returns one follow-up message after the first stop; assert `read_file`/`write_file` calls appear only once and `bash` appears after them |

## Order of operations

1. Read `src/agent.py` outer loop to locate the current `break` statement and the existing `pending_messages` list and flush logic.
2. Add `get_steering_messages=None` parameter to `run_agent`. After the inner loop exits, if `get_steering_messages` is not None, `await` it and extend `pending_messages` with the returned messages. Continue the outer loop if `pending_messages` is non-empty; break otherwise.
3. Confirm the existing `pending_messages` flush at the top of the inner loop (`if pending_messages: messages.extend(...); pending_messages.clear()`) is already in place. If not, add it.
4. Write `tests/test_steering.py`: craft a `ScriptedLLM` (or mock) that yields a stop-turn on first call, then a bash-tool-call turn on second call. Provide `get_steering_messages` that returns `[{"role": "user", "content": "now run the tests"}]` exactly once (return `[]` on subsequent calls). Assert tool call counts and ordering in the final `messages` list.
5. Run BDD gate red (outer loop still has unconditional `break`) then green (after the change).

## Verification

- [ ] Tests added: `tests/test_steering.py`
- [ ] Run: `uv run pytest tests/test_steering.py -v`
- [ ] Manual verification:
  1. `uv run main.py "create a file called hello.py with a hello function"`
  2. After agent stops, inject a follow-up via the configured steering channel (stdin, queue, or `steer()` in the SDK).
  3. Confirm agent resumes and completes the follow-up.
  4. Inspect message history: prior tool calls must not be re-executed.
- [ ] BDD acceptance:

```gherkin
Scenario: Steering continues the agent without replaying prior tool calls
  Given the agent has completed a task using read_file and write_file
  When a follow-up message is injected via the steering API asking to run the tests
  Then the agent continues from where it left off
  And the prior read_file and write_file calls are not replayed
  And the agent executes a bash tool call for the test run
```

## Notes / open questions

- THIS IS A PLANNED EXTENSION — not part of v1. The outer loop `break` exists in `agent.py` today; what is missing is the mechanism to push messages into `pending_messages` from outside the loop while it is running.
- Three implementation options for the input channel are described in the tutorial: (a) asyncio.Queue fed by the caller concurrently, (b) between-tool-call polling via `get_steering_messages`, (c) external RPC signal. This plan implements option (b) as the lowest-friction starting point.
- The injected callable approach keeps `run_agent`'s interface clean: the loop does not know whether messages come from a stdin reader, a queue, or a test fixture — it only sees a list.
- True concurrent injection (option a, queue-based) is needed for real-time steering while the agent is mid-tool-call; that requires `asyncio.Queue` and concurrent task management — scope that as a follow-on if option (b) proves insufficient.
- The SDK's `run_agent_collecting` wrapper (Phase 14.1) will need to thread `get_steering_messages` through to `run_agent` once this is implemented.

---

**Tutorial build step 30 of 32** · ← [Phase 14.3 — JSON Event Stream](./phase-14-3-json-event-stream.md) · [Phase 16 — Context Compaction](./phase-16-context-compaction.md) →
