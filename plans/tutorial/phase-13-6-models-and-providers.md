Status: not started

# Phase 13.6 — Custom Models & Providers

## Goal

Make `MODEL` in `src/provider.py` configurable via `AGENT_MODEL` env var and a `--model` CLI flag, and add a `USE_CLAUDE_CLI_LLM=1` fork that shells out to `claude -p` instead of LiteLLM — without changing the agent loop.

## Files changed

| File | Change |
|---|---|
| `src/provider.py` | Read `MODEL` from `AGENT_MODEL` env var; accept optional `model` param in `stream_response`; add `USE_CLAUDE_CLI` branch with `_claude_cli_stream` async generator |
| `src/agent.py` | Thread optional `model: str | None` param through `run_agent` → `stream_response` call |
| `main.py` | Add `--model` argparse flag; pass `args.model` to `run_agent`; add `load_dotenv()` call |
| `tests/test_provider.py` | New/updated tests — `model` override passed to `litellm.acompletion`; `USE_CLAUDE_CLI_LLM=1` calls `_claude_cli_stream` not `litellm`; mock subprocess yields correct chunk shape; no env var keeps original default |

## Order of operations

1. Write a failing test: calling `stream_response(messages, sp, model="gpt-4o")` should invoke `litellm.acompletion` with `model="gpt-4o"`. Confirm the current code ignores the param.
2. Update `src/provider.py` to read `MODEL = os.environ.get("AGENT_MODEL", "claude-sonnet-4-5")` and use `effective_model = model or MODEL` in `stream_response`. Run test — green.
3. Write test: `USE_CLAUDE_CLI_LLM=1` causes `stream_response` to skip `litellm.acompletion` entirely. Add `USE_CLAUDE_CLI` constant and the branch. Run test.
4. Write test: `_claude_cli_stream` yields chunks shaped like `SimpleNamespace(choices=[SimpleNamespace(delta=..., finish_reason=...)])` — mock `asyncio.create_subprocess_exec`. Run test.
5. Add `model: str | None = None` param to `run_agent` in `src/agent.py`; pass it to `stream_response` inside the loop. Run `uv run pytest -q`.
6. Add `--model` flag to `main.py` argparse; pass `args.model` to `run_agent`; add `load_dotenv()` at the top. Run full suite.
7. Smoke-test with a real alternate model if credentials are available.

## Verification

- [ ] Tests added/updated: `tests/test_provider.py`
- [ ] Full suite: `uv run pytest -q` — no env overrides means `MODEL="claude-sonnet-4-5"` and `USE_CLAUDE_CLI=False`; existing mocks of `litellm.acompletion` continue to work
- [ ] Default: `uv run main.py "list the files in src/"` — unchanged behavior
- [ ] Env override: `AGENT_MODEL=gpt-4o uv run main.py "add type hints to tools.py"` — routes to OpenAI (requires `OPENAI_API_KEY`)
- [ ] CLI flag: `uv run main.py --model gemini/gemini-2.0-flash "explain the agent loop"` — routes to Gemini (requires `GEMINI_API_KEY`)
- [ ] Local Ollama: `AGENT_MODEL=ollama/llama3.2 uv run main.py "summarize this repo"` — no API key required
- [ ] CLI backend: `USE_CLAUDE_CLI_LLM=1 uv run main.py "explain what src/agent.py does"` — shells out to `claude -p`, text-only response

### Acceptance (BDD)

```gherkin
Scenario: Changing MODEL routes to a different provider; USE_CLAUDE_CLI_LLM routes via claude -p
  Given the default MODEL is "claude-sonnet-4-5"
  When stream_response is called with model="gpt-4o"
  Then litellm.acompletion is called with model="gpt-4o"
  And the agent loop receives the same OpenAI-format chunk stream
  And the tool dispatch and message history are unchanged

  Given USE_CLAUDE_CLI_LLM=1 is set in the environment
  When stream_response is called
  Then _claude_cli_stream is called instead of litellm.acompletion
  And a claude subprocess is spawned with the -p flag
  And text chunks from the CLI are yielded in the same OpenAI-format shape
```

## Notes / open questions

- CLI backend (`USE_CLAUDE_CLI_LLM=1`) is text-only in this form — `TOOLS_SCHEMA` is not forwarded to `claude -p`. Full tool-calling parity requires translating the stream-json protocol (deferred to the architecture patterns section).
- `python-dotenv` must be added as a dependency; `load_dotenv()` in `main.py` loads `.env` at startup for API keys.
- `MAX_TOKENS` is also read from `AGENT_MAX_TOKENS` env var — defaults to 8096.
- Provider reference table: `claude-sonnet-4-5` (Anthropic/`ANTHROPIC_API_KEY`), `gpt-4o` (OpenAI/`OPENAI_API_KEY`), `gemini/gemini-2.0-flash` (Google/`GEMINI_API_KEY`), `ollama/llama3.2` (local/no key), `bedrock/claude-sonnet-4-5` (AWS/`AWS_*`).

---

**Tutorial build step 26 of 32** · ← [Phase 13.5 — MCP Integration](./phase-13-5-mcp-integration.md) · [Phase 14.1 — The SDK](./phase-14-1-sdk.md) →
