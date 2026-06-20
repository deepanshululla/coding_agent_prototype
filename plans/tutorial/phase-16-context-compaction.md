Status: not started

# Phase 16 — Context Compaction

## Goal

Prevent the agent from crashing on context-window overflow by inserting a `compact_if_needed(messages, system_prompt)` hook in the inner loop before every `stream_response` call; the hook returns a (possibly shorter) message list without mutating the source-of-truth `messages` list, using a threshold ladder to choose between three compaction strategies.

## Files changed

| File | Change |
|---|---|
| `src/compaction.py` | New file — `async def compact_if_needed(messages, system_prompt) -> list[dict]`; implements token estimation and three strategy ladder: passthrough (<100k), drop stale tool results (100k–160k), summarise old turns via LLM call (160k–190k), keep recent turns only (>190k) |
| `src/agent.py` | Inner loop: replace `async for chunk in stream_response(messages, ...)` with `context_to_send = await compact_if_needed(messages, system_prompt)` then `async for chunk in stream_response(context_to_send, ...)` — `messages` never passed to `compact_if_needed` by reference for mutation |
| `tests/test_compaction.py` | New file — patches `TOKEN_BUDGET` to a low value to force triggering; monkeypatches `compact_if_needed` to record calls; asserts `len(context_to_send) < len(messages)` after trigger turn; asserts final answer still references a fact from early in the conversation |

## Order of operations

1. Decide on a token estimation approach: a lightweight character-count heuristic (`len(json.dumps(messages)) // 4`) or `tiktoken` if already available. Use the heuristic first; it requires no extra dependency.
2. Create `src/compaction.py` with `compact_if_needed`. At the passthrough threshold, return `messages` unchanged (no allocation). Implement drop-stale-tool-results: iterate messages, keep all non-tool-result messages plus the most recent N tool results. Stub summarise and keep-recent strategies with `raise NotImplementedError` initially; implement them before the BDD gate.
3. Add the `compact_if_needed` call in `src/agent.py` inner loop, importing from `compaction`. Keep `messages` unmutated — `compact_if_needed` receives a reference and must return a new list when shortening.
4. Write `tests/test_compaction.py`: patch `compaction.TOKEN_BUDGET` (or equivalent threshold constant) to 500 tokens. Build a `messages` list long enough to exceed it. Call `compact_if_needed` directly and assert the returned list is shorter. Then run a full mocked `run_agent` and assert `stream_response` receives the compacted list, not the full one.
5. Run BDD gate: without the hook, the scenario's padded history is passed unchanged to `stream_response` (red). After, `len(context_to_send) < len(messages)` (green).

## Verification

- [ ] Tests added: `tests/test_compaction.py`
- [ ] Run: `uv run pytest tests/test_compaction.py -v`
- [ ] Manual verification:
  1. Patch `TOKEN_BUDGET = 500` temporarily in `compaction.py`.
  2. `uv run main.py "read three files and summarize them"`.
  3. Observe log/emit event indicating compaction triggered.
  4. Confirm history length before vs. after the compaction turn.
  5. Ask follow-up requiring early-session fact; confirm correct answer.
- [ ] BDD acceptance:

```gherkin
Scenario: Compaction keeps the agent coherent after a long task
  Given a long task whose message history exceeds the compaction threshold
  When the agent continues after compaction triggers
  Then the context sent to the model is shorter than the full message history
  And the agent proceeds coherently without losing the essential facts from prior turns
```

## Notes / open questions

- THIS IS A PLANNED FEATURE — not part of v1. The current agent has no compaction logic; `messages` grows without bound until an API error occurs.
- The source-of-truth `messages` list must never be mutated by compaction — this is the key invariant. `compact_if_needed` always returns either `messages` itself (passthrough) or a new shorter list.
- Token estimation: the `len(json.dumps(messages)) // 4` heuristic is fast and dependency-free. LiteLLM exposes `litellm.token_counter(model, messages)` as a more accurate alternative — evaluate whether the extra call latency is worth it.
- The summarise strategy (160k–190k) requires a second LLM call and costs tokens. Cache the summary between turns if the history hasn't changed since the last compaction.
- The threshold ladder constants (`100k`, `160k`, `190k`) should be configurable via env vars (`COMPACT_SOFT_THRESHOLD`, `COMPACT_HARD_THRESHOLD`, etc.) so they can be lowered in tests without code changes.
- Compaction should emit a `compaction` typed event via `emit()` so the event stream and TUI can surface it to the user.
- Pairs with Phase 15 steering: steered sessions that run many turns are the primary driver of context overflow. Implement Phase 15 first.

---

**Tutorial build step 31 of 32** · ← [Phase 15 — Steering](./phase-15-steering.md) · [Phase 17 — Extended Thinking](./phase-17-extended-thinking.md) →
