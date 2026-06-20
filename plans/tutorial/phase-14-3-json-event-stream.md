Status: not started

# Phase 14.3 — JSON Event Stream

## Goal

Add `AGENT_OUTPUT=json` to `renderer.py` so every `emit()` call is serialised as a newline-delimited JSON object on stdout, and wire that stream into the `POST /run_agent/stream` HTTP endpoint so log pipelines, dashboards, and streaming HTTP clients get structured output without parsing human-readable text.

## Files changed

| File | Change |
|---|---|
| `src/renderer.py` | Add `AGENT_OUTPUT` env-var check at top of selector: when `AGENT_OUTPUT == "json"`, define `emit` as `lambda event: print(json.dumps(event), flush=True)`; all other branches unchanged |
| `http_server.py` | Replace stub `/run_agent/stream` endpoint with one that calls `run_agent_collecting(req.task)` from `sdk.py` and yields `json.dumps(event) + "\n"` for each collected event |
| `tests/test_json_event_stream.py` | New file — patches `AGENT_OUTPUT=json`, reloads renderer, runs `run_agent_collecting` with a mocked two-iteration stream (text + tool call), asserts each event type is present, `agent_end` is last, and `tool_call_start` precedes matching `tool_call_end` |

## Order of operations

1. Read `src/renderer.py` to see the current `AGENT_UI` selector structure.
2. Add `import json as _json` and `_OUTPUT = os.getenv("AGENT_OUTPUT", "")` at the top of `renderer.py`. Prepend an `if _OUTPUT == "json":` branch that defines `emit` as the NDJSON printer; leave all existing `elif` / `else` branches in place below it.
3. Smoke-test: `AGENT_OUTPUT=json uv run main.py "list the files in src/"` — confirm each stdout line is valid JSON and that `jq -r '.type'` shows the expected type sequence.
4. Update `http_server.py` `/run_agent/stream` endpoint: import `run_agent_collecting` from `sdk`; define `event_lines()` as an async generator that awaits `run_agent_collecting(req.task)` then yields each event as NDJSON; return `StreamingResponse(event_lines(), media_type="application/x-ndjson")`.
5. Write `tests/test_json_event_stream.py` with `@patch.dict(os.environ, {"AGENT_OUTPUT": "json"})`, `importlib.reload(renderer)` to pick up the env var, a `fake_stream_with_tool` async generator mock, and assertions on event ordering.
6. Run BDD gate: before the renderer change, `json.loads` raises `JSONDecodeError` on human-readable lines (red). After, every line parses cleanly (green).

## Verification

- [ ] Tests added: `tests/test_json_event_stream.py`
- [ ] Run: `uv run pytest tests/test_json_event_stream.py -v`
- [ ] `jq` pipeline smoke test:
  ```bash
  AGENT_OUTPUT=json uv run main.py "list the files in src/" | jq -r '.type'
  ```
  Expected sequence for a two-iteration run: `text_delta`, `tool_call_start`, `tool_call_end`, `turn_end`, `text_delta`, `turn_end`, `agent_end`
- [ ] HTTP streaming endpoint:
  ```bash
  curl -s -X POST http://127.0.0.1:8000/run_agent/stream \
    -H "Content-Type: application/json" \
    -d '{"task": "list the files in src/"}' | jq -r '.type'
  ```
- [ ] BDD acceptance:

```gherkin
Scenario: Piping AGENT_OUTPUT=json through jq shows all event types in order
  Given AGENT_OUTPUT=json is set in the environment
  And stream_response is mocked to return a stop chunk with text and one tool call
  When the agent is run and its stdout is captured line by line
  Then each line is a valid JSON object (json.loads succeeds)
  And the event types appear in this order:
       text_delta, tool_call_start, tool_call_end, turn_end, text_delta, turn_end, agent_end
  And no text_delta event appears after the agent_end event
  And the tool_call_start event is immediately followed (with possible text_deltas)
       by a tool_call_end event with the same tool_call_id
```

## Notes / open questions

- The `importlib.reload(renderer)` trick in tests is required because renderer selects the emitter at import time based on the env var; reloading forces re-evaluation under the patched env. Alternatively, expose `_select_emit()` as a function to make this testable without reload.
- The `/run_agent/stream` endpoint is collect-then-flush (no true streaming): `run_agent_collecting` waits for the agent to finish before yielding events. True real-time streaming requires an `asyncio.Queue` wired into the emit seam — deferred to Phase 15 (steering) where the queue becomes structurally necessary.
- `AGENT_OUTPUT=json` and `AGENT_UI=tui` are intentionally independent axes; the renderer branch order (json check first, then UI) means JSON output takes precedence and suppresses TUI rendering.

---

**Tutorial build step 29 of 32** · ← [Phase 14.2 — RPC Mode](./phase-14-2-rpc-mode.md) · [Phase 15 — Steering](./phase-15-steering.md) →
