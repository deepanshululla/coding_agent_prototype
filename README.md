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

Swap providers by setting `AGENT_MODEL` in `.env` or using the `--model` flag:
```bash
uv run main.py --model gpt-4o "explain the agent loop"                # OpenAI
uv run main.py --model gemini/gemini-2.0-flash "count Python files"   # Google
uv run main.py --model ollama/llama3.2 "summarize tools.py"           # Ollama (local)
```

For Ollama, use the convenient `--ollama` shorthand (adds the `ollama/` prefix):
```bash
uv run main.py --ollama llama3.2 "summarize tools.py"         # Same as --model ollama/llama3.2
uv run main.py --ollama "fix the bug"                         # Uses ollama/llama3.2 by default
```

Set the matching API key in `.env` (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`).
For Ollama, no API key is needed — just run `ollama serve` and pull your model first
(`ollama pull llama3.2`).

### TUI Mode

Launch the full-screen TUI with `AGENT_UI=tui`:
```bash
AGENT_UI=tui uv run main.py "start task"           # Uses AGENT_MODEL from .env
AGENT_UI=tui uv run main.py --model gpt-4o         # Override model for this session
AGENT_UI=tui uv run main.py --ollama llama3.2      # Use Ollama (adds ollama/ prefix)
AGENT_UI=tui uv run main.py --ollama               # Use default ollama/llama3.2
```

**TUI Keybindings:**
- `i` — enter insert mode (focus input box)
- `Esc` — return to normal mode
- `:` — enter command mode
- `j/k` — scroll down/up (normal mode)
- `g g` — scroll to top, `G` — scroll to bottom
- `Ctrl+C` — copy selected text (when transcript focused with selection), or cancel current turn
- `Ctrl+A` — select all text in transcript (when transcript focused)
- `Shift+Tab` — cycle permission mode (auto/edit/plan)
- `Ctrl+V` — paste image from clipboard (multimodal models can analyze pasted screenshots)
- `Ctrl+Q` — quit

**TUI Slash Commands:**
Type these in insert mode (prefixed with `/`) to run local commands without sending to the agent:
- `/help` — list all available commands
- `/model` — show current model, or `/model <name>` to switch
- `/skill` — list installed skills, or `/skill <name>` to load one
- `/usage` — show session stats (model/tool calls, elapsed time, tokens)

**Autocomplete:**
When typing a slash command, press `Tab` to cycle through matching commands:
- Type `/` and press `Tab` to cycle through all commands
- Type `/mo` and press `Tab` to complete to `/model`
- Press `Shift+Tab` to cycle backward through completions

**Image Support:
The agent can work with images in two ways:
- **Paste from clipboard**: Use `Ctrl+V` in TUI mode to attach an image to your next message. Pasted images are displayed inline in the transcript with metadata (format and size).
- **Read image files**: The `read_file` tool automatically detects image extensions (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, etc.) and returns base64-encoded data

Both methods send images to multimodal models (Claude, GPT-4V, Gemini Vision) for analysis. In TUI mode, images are shown as styled placeholders with format and size information.

When using `USE_CLAUDE_CLI_LLM=1` mode (routing through `claude -p` subprocess), pasted images are automatically saved to temporary files and referenced by path in the prompt, allowing the CLI fork to read them via its file reading capability. Temp files are cleaned up after each turn.

### Architectures

The agent's control-flow strategy is pluggable. Pick one per run with
`--architecture` (or the `AGENT_ARCHITECTURE` env var); unknown names fall back
to `reactive` with a warning.

```bash
uv run main.py --architecture reactive            "fix the bug in tools.py"   # default single loop
uv run main.py --architecture orchestrator-worker "audit the whole src/ tree" # split → workers → synthesize
uv run main.py --architecture evaluator-optimizer "write a tricky regex"      # answer → critic → revise
uv run main.py --architecture planner-executor    "scaffold a new feature"    # plan → run steps in order
```

All four compose the same primitives (`stream_turn`, `execute_tools`); the
alternates trade extra model calls for decomposition, self-critique, or
up-front planning. Add your own by subclassing `AgentArchitecture` and decorating
it with `@register("name")` in `src/architectures/`.

## Layout

```
src/
  types_.py    # ToolCall, ToolResult, Message dataclasses (types_ avoids shadowing stdlib)
  tools.py     # 7 tools: read/write/edit_file, bash, grep, find_files, list_dir
               # (read_file auto-detects images and returns base64 JSON)
  prompts.py   # build_system_prompt(cwd, extra) — dynamic CWD + date + tool list
  provider.py  # stream_response() — one litellm.acompletion stream, any provider
  agent.py     # run_agent() facade + stream_turn/execute_tools primitives + ReactiveAgent
  architecture.py    # AgentArchitecture Protocol, RunContext, registry (the pluggable seam)
  architectures/     # orchestrator-worker, evaluator-optimizer, planner-executor
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
