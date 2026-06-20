Status: not started

# Phase 14.2 — RPC Mode

## Goal

Wrap `run_agent` in two process-boundary interfaces — a one-shot stdin/stdout JSON-RPC 2.0 server (`rpc_server.py`) and a persistent FastAPI-on-Granian HTTP server (`http_server.py`) — so callers in any language can drive the agent without importing Python.

## Files changed

| File | Change |
|---|---|
| `rpc_server.py` | New file at repo root — reads one JSON-RPC 2.0 request from stdin, calls `run_agent(task)`, writes one JSON-RPC 2.0 response to stdout, then exits |
| `http_server.py` | New file at repo root — FastAPI app with `POST /run_agent` (sync) and `POST /run_agent/stream` (stub NDJSON, completed in 14.3); served by Granian |
| `tests/test_rpc_server.py` | New file — subprocess integration test: spawns `rpc_server.py` with a mocked agent via `MOCK_AGENT=1`, asserts stdout is valid JSON-RPC 2.0 with `result.status == "ok"` |
| `pyproject.toml` | Add `fastapi` and `granian` dependencies via `uv add fastapi granian` |

## Order of operations

1. Install dependencies: `uv add fastapi granian`.
2. Create `rpc_server.py`: `sys.path.insert(0, "src")`, `load_dotenv()`, read one line from stdin, `json.loads`, extract `params.task`, `await run_agent(task)` in try/except, write JSON-RPC 2.0 response dict to stdout via `print(json.dumps(response), flush=True)`.
3. Smoke-test manually: `echo '{"jsonrpc":"2.0","id":"1","method":"run_agent","params":{"task":"say hello"}}' | AGENT_UI=none uv run rpc_server.py` — confirm a JSON response line appears.
4. Create `http_server.py`: FastAPI app, `RunRequest` Pydantic model with `task`, optional `model`, optional `max_iterations`; `POST /run_agent` calls `run_agent` and returns status + message_count; `POST /run_agent/stream` is a stub that emits a single `agent_end` NDJSON line (will be completed in 14.3).
5. Write `tests/test_rpc_server.py` using `subprocess.run` with `AGENT_UI=none` and `MOCK_AGENT=1`; assert returncode 0, stdout parses as valid JSON, `jsonrpc == "2.0"`, `result.status == "ok"`, `result.message_count > 0`.
6. Run BDD gate: confirm test fails before `rpc_server.py` exists (FileNotFoundError), passes after.

## Verification

- [ ] Tests added: `tests/test_rpc_server.py`
- [ ] Run: `uv run pytest tests/test_rpc_server.py -v -m integration`
- [ ] Manual stdin/stdout run:
  ```bash
  echo '{"jsonrpc":"2.0","id":"1","method":"run_agent","params":{"task":"say hello"}}' \
    | AGENT_UI=none uv run rpc_server.py
  ```
- [ ] Manual HTTP run:
  ```bash
  granian --interface asgi http_server:app --host 127.0.0.1 --port 8000 --workers 1 &
  curl -s -X POST http://127.0.0.1:8000/run_agent \
    -H "Content-Type: application/json" \
    -d '{"task": "list the files in src/"}'
  ```
- [ ] BDD acceptance:

```gherkin
Scenario: JSON-RPC request on stdin runs the agent and returns a structured response
  Given rpc_server.py exists at the repo root
  And stream_response is mocked to return a single stop chunk with text "hello"
  When a valid JSON-RPC 2.0 request is written to rpc_server.py's stdin
  Then the process exits with code 0
  And stdout contains exactly one line of valid JSON
  And the JSON has "jsonrpc" equal to "2.0"
  And the JSON has "result.status" equal to "ok"
  And "result.message_count" is a positive integer
```

## Notes / open questions

- `rpc_server.py` prints agent output on stderr (or suppresses it via `AGENT_UI=none`) so it does not corrupt the JSON response channel on stdout. This is an intentional limitation of the v1 design — the clean fix (NDJSON events on one channel) is implemented in Layer 14.3.
- HTTP server must bind to `127.0.0.1`, not `0.0.0.0` — the agent runs arbitrary bash commands. Document this constraint in a comment in `http_server.py`.
- `run_agent` builds `messages` as a local per-call, so concurrent HTTP requests do not share history. The only shared mutable state is `MODEL` in `provider.py`; make it a per-request parameter to make concurrent calls fully independent.
- The `/run_agent/stream` endpoint is a stub here; it will be wired to `run_agent_collecting` in Phase 14.3.

---

**Tutorial build step 28 of 32** · ← [Phase 14.1 — The SDK](./phase-14-1-sdk.md) · [Phase 14.3 — JSON Event Stream](./phase-14-3-json-event-stream.md) →
