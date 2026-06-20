# Coding Agent From Scratch

A real terminal coding agent in ~750 lines of Python. No framework — the agent *is* a
loop: send the conversation to a model, let it call tools, feed the results back, repeat
until it's done. Grounded in Harkirat Singh's Super 30 lecture and the
[pi.dev](https://github.com/earendil-works/pi) source, with [LiteLLM](https://docs.litellm.ai/)
standing in for a 40-provider abstraction layer.

## Install

```bash
uv sync                       # installs litellm + python-dotenv (and pytest for dev)
echo "ANTHROPIC_API_KEY=sk-..." > .env
```

## Run

```bash
uv run main.py "add type hints to all functions in src/tools.py"
uv run main.py "list all .py files and count the lines in each"
```

Swap providers by changing one string (`MODEL` in `src/provider.py`):
`claude-sonnet-4-5` → Anthropic, `gemini/gemini-2.0-flash` → Google, `gpt-4o` → OpenAI.
Set the matching API key (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`).

## Layout

```
src/
  types_.py    # ToolCall, ToolResult, Message dataclasses (types_ avoids shadowing stdlib)
  tools.py     # 7 tools: read/write/edit_file, bash, grep, find_files, list_dir
  prompts.py   # build_system_prompt(cwd, extra) — dynamic CWD + date + tool list
  provider.py  # stream_response() — one litellm.acompletion stream, any provider
  agent.py     # run_agent() — the inner/outer loop, streaming accumulation, parallel tools
main.py        # CLI entrypoint
tests/         # test_tools.py (units), test_agent.py (loop with a mocked model)
```

## Test

```bash
uv run pytest            # 17 tests: 13 tool units + 4 mocked-loop integration tests
```

## How it works

The inner loop streams a model response, executes any requested tool calls **in parallel**
(`asyncio.gather`), appends the results as `role: "tool"` messages, and continues until the
model returns text with no tool calls. Tool-call arguments arrive as partial JSON across
stream chunks — they're buffered by `index` and parsed only once the stream ends. Tools
never raise; they return error strings so the model can reason and recover.

Full documentation lives in [`website/`](website/) (a Docusaurus site):

```bash
task docs:dev      # serve the docs at http://localhost:3000
task docs:build    # build the static site
```

## Status

The core loop, all 7 tools, the provider layer, prompts, the CLI, and the test suite are
implemented. Advanced features (steering, context compaction, hooks, skills, extended
thinking, session persistence, RPC / JSON event-stream modes) are designed in the docs but
not yet built — see `website/docs/differences-from-pi.md` and `PLAN.md`.
