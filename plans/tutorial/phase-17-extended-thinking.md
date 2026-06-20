Status: not started

# Phase 17 — Extended Thinking

## Goal

Enable the model's extended thinking mode for hard multi-step problems by passing the `thinking` parameter in `provider.py`, accumulating a `thinking_buf` alongside `text_buf` in `agent.py`, and preserving `ThinkingContent` blocks verbatim (with `signature`) in the assistant message — without showing the scratchpad in normal stdout output.

## Files changed

| File | Change |
|---|---|
| `src/provider.py` | Add `thinking={"type": "enabled", "budget_tokens": THINKING_BUDGET}` to `litellm.acompletion` call; increase `max_tokens` to at least `THINKING_BUDGET + 2000`; make both values configurable via env vars `THINKING_BUDGET` and `MAX_TOKENS` |
| `src/agent.py` | Add `thinking_buf = ""` alongside `text_buf`; in the streaming accumulation loop, check `if hasattr(delta, "thinking") and delta.thinking: thinking_buf += delta.thinking`; build `assistant_msg["content"]` as a list: `[{"type": "thinking", "thinking": thinking_buf, "signature": ...}, {"type": "text", "text": text_buf}]` when thinking is non-empty; preserve thinking blocks verbatim in history |
| `tests/test_extended_thinking.py` | New file — mock stream includes a delta with `.thinking = "my reasoning"` before the text delta; assert `assistant_msg["content"]` is a list, first element has `type == "thinking"`, `thinking_buf` is non-empty |

## Order of operations

1. Add `THINKING_BUDGET` and `MAX_TOKENS` env var reads to `provider.py` (default: `0` and `8096`). When `THINKING_BUDGET > 0`, include `thinking={"type": "enabled", "budget_tokens": THINKING_BUDGET}` in the `litellm.acompletion` call and set `max_tokens = max(MAX_TOKENS, THINKING_BUDGET + 2000)`.
2. In `src/agent.py` inner accumulation loop, add the `thinking_buf` accumulator and the `hasattr(delta, "thinking")` guard (safe to add even when thinking is disabled — guard short-circuits).
3. Update the assistant message construction: when `thinking_buf` is non-empty, set `content` to `[{"type": "thinking", "thinking": thinking_buf}, {"type": "text", "text": text_buf}]` instead of a plain string. When `thinking_buf` is empty (thinking disabled), keep backward-compatible plain string or `[{"type": "text", "text": text_buf}]`.
4. Emit `thinking_buf` to a debug channel (e.g., a `thinking_delta` event via `emit()`, or a debug log) — do not print to normal stdout.
5. Write `tests/test_extended_thinking.py`: mock a `ScriptedLLM` chunk that has `delta.thinking = "step 1: plan"` and `delta.content = "Here is the result"`. Run `run_agent_collecting("hard problem")`. Assert the final assistant message in history has `content` as a list, `content[0]["type"] == "thinking"`, `content[0]["thinking"]` is non-empty, and `content[1]["type"] == "text"`.
6. Run BDD gate: without the `thinking_buf` accumulator, `thinking` field on delta is silently ignored and `content[0]` is not a thinking block (red). After, it passes (green).

## Verification

- [ ] Tests added: `tests/test_extended_thinking.py`
- [ ] Run: `uv run pytest tests/test_extended_thinking.py -v`
- [ ] Manual verification:
  1. Set `THINKING_BUDGET=2000` and `MAX_TOKENS=4000` in `.env`.
  2. `uv run main.py "refactor the tools module so each tool is in its own file"`.
  3. Inspect raw message history after run: first assistant message `content` must be a list with `content[0]["type"] == "thinking"`.
  4. Confirm thinking trace is non-empty and coherent in the debug log.
- [ ] BDD acceptance:

```gherkin
Scenario: Extended thinking produces a reasoning trace before the final answer
  Given extended thinking is enabled with a budget of 8000 tokens
  And the agent is given a multi-step planning problem
  When the agent runs to completion
  Then the assistant message history contains a thinking block before the text block
  And the final answer reflects reasoning established in the thinking block
```

## Notes / open questions

- THIS IS A PLANNED EXTENSION — not part of v1. The current `stream_response()` call in `provider.py` does not pass `thinking`, and the streaming accumulator in `agent.py` does not handle `ThinkingContent` blocks.
- Block order matters: the API requires `thinking` block before `text` or `tool_use` block in `content`. The message construction must enforce this order.
- The `signature` field on `ThinkingContent` must be echoed back verbatim in subsequent turns — do not drop or summarise it. Check LiteLLM docs for how `signature` surfaces in the streaming delta.
- `max_tokens` must exceed `budget_tokens`; the v1 default of 8096 is not sufficient when `budget_tokens = 8000`. Guard against misconfiguration with an assertion: `assert max_tokens > budget_tokens`.
- Extended thinking is not free: each thinking turn costs `budget_tokens` additional tokens even if the model does not use all of them. Leave it disabled by default (`THINKING_BUDGET=0`) and document clearly when it earns its keep (multi-step planning, architectural refactors).
- Context compaction (Phase 16) must not drop or summarise thinking blocks — they must be preserved verbatim. Note this interaction when implementing Phase 16's drop-stale-tool-results strategy.
- Only some Claude models support extended thinking (e.g., `claude-sonnet-4-5` but not all LiteLLM aliases). Add a model compatibility guard in `provider.py`.

---

**Tutorial build step 32 of 32** · ← [Phase 16 — Context Compaction](./phase-16-context-compaction.md) · _(last step)_
