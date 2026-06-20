# Coding Agent From Scratch — Implementation Plan

Grounded in two sources:
- Harkirat Singh's Super 30 lecture ("How Modern AI Agents Work Under the Hood")
- pi.dev source code (github.com/earendil-works/pi, TypeScript, ~46k stars)

---

## Mental Model

```
User task
   │
   ▼
┌──────────────────────────────────────────┐
│              OUTER LOOP                  │  ← handles follow-up messages
│  ┌────────────────────────────────────┐  │
│  │           INNER LOOP               │  │  ← the core agent loop
│  │  sendMessage → stream response     │  │
│  │  if tool_calls → execute all       │  │
│  │  push results → continue           │  │
│  │  if end_turn  → break inner        │  │
│  └────────────────────────────────────┘  │
│  if follow-up messages → continue outer  │
│  else → break outer                      │
└──────────────────────────────────────────┘
```

**Key insight from lecture:** The agent IS this loop. LangChain/LangGraph just export this abstraction. Pi.dev's agent-core package is < 750 lines.

**Key insight from pi.dev source:** Tool execution is parallel by default. The inner loop checks for both remaining tool calls AND pending steering messages. The outer loop exists only for follow-up messages queued after the agent would otherwise stop.

---

## File Layout

```
coding_agent_from_scratch/
├── src/
│   ├── agent.py         # The while-loop (inner + outer), streaming, tool dispatch
│   ├── tools.py         # 7 tool definitions (schema dicts) + async implementations
│   ├── prompts.py       # System prompt builder (dynamic: CWD, date, tool list)
│   ├── provider.py      # LiteLLM wrapper — one async stream_response() function
│   └── types_.py        # Dataclasses for ToolCall, ToolResult  (types.py shadows stdlib)
├── tests/
│   ├── test_tools.py    # Unit tests for each tool function
│   └── test_agent.py    # Integration tests for the agent loop (mock LLM)
├── docs/
│   └── architecture.md  # How the loop works, how to add a new tool
├── main.py              # CLI entrypoint — asyncio.run(run_agent(task))
├── pyproject.toml
├── .env                 # ANTHROPIC_API_KEY=sk-...
└── PLAN.md              # This file
```

**Why these folders?**
- `src/` — keeps importable code separate from the entrypoint and config; mirrors pi's `packages/`
- `tests/` — tools are pure functions and easy to unit-test without an LLM
- `docs/` — one architecture doc is enough; explains the loop for anyone reading later

**Import note:** Since `src/` is not a package (no `__init__.py`), add it to `sys.path` in `main.py`, or configure `pyproject.toml` with `pythonpath = ["src"]` under `[tool.pytest.ini_options]` for tests.

---

## Dependencies

```bash
uv add litellm python-dotenv
```

LiteLLM replaces pi.dev's entire `packages/ai/` provider abstraction layer (40+ provider adapters). Swap models by changing one string — `"claude-sonnet-4-5"`, `"gemini/gemini-2.0-flash"`, `"gpt-4o"` — all work identically. It normalizes every provider's response to OpenAI's format.

`subprocess`, `pathlib`, `glob`, `json`, `os`, `sys`, `re`, `concurrent.futures` are all stdlib.

---

## Step-by-Step Implementation

### Step 1 — `types.py`

Define the data structures that flow through the system. Mirror pi's message types closely.

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

@dataclass
class ToolResult:
    tool_call_id: str
    tool_name: str
    content: str
    is_error: bool = False

@dataclass
class Message:
    role: str            # "user" | "assistant" | "tool_result"
    content: str | list  # str for user, list of blocks for assistant/tool
```

Pi uses a richer type hierarchy (TextContent, ThinkingContent, ImageContent, ToolCall blocks). For v1, plain dicts in the `content` list are enough — the Anthropic SDK accepts them directly.

---

### Step 2 — `tools.py`

Pi implements 7 tools: `read`, `bash`, `edit`, `write`, `grep`, `find`, `ls`.

Each tool needs:
1. A **JSON schema dict** (passed to the API in `tools=`)
2. A **Python function** (executed by the agent loop)
3. An entry in `TOOL_REGISTRY` (name → callable)

LiteLLM expects **OpenAI-style** tool schemas (`type: "function"` wrapper + `parameters` key), not Anthropic's `input_schema`. LiteLLM translates internally to whatever the provider needs.

```python
# Pattern for each tool
async def read_file(path: str, offset: int = 0, limit: int = 2000) -> str:
    ...

TOOLS_SCHEMA = [
    {
        "type": "function",          # required by OpenAI format (LiteLLM standard)
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file. Use offset/limit for large files.",
            "parameters": {          # "parameters" not "input_schema"
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"},
                    "offset": {"type": "integer", "description": "Line to start from (0-indexed)", "default": 0},
                    "limit": {"type": "integer", "description": "Max lines to return", "default": 2000},
                },
                "required": ["path"],
            },
        },
    },
    # ... one entry per tool
]

TOOL_REGISTRY: dict[str, callable] = {
    "read_file": read_file,
    "bash": bash,
    "edit_file": edit_file,
    "write_file": write_file,
    "grep": grep,
    "find_files": find_files,
    "list_dir": list_dir,
}
```

#### The 7 implementations

| Tool | Implementation | Notes |
|------|---------------|-------|
| `read_file` | `Path(path).read_text()` with line slicing | Return error string on failure, never raise |
| `bash` | `subprocess.run(cmd, shell=True, capture_output=True, timeout=30)` | Truncate output to 10k chars; include exit code |
| `edit_file` | Find `old_string`, replace with `new_string` | Return error if `old_string` not found or not unique |
| `write_file` | `Path(path).write_text(content)` | `mkdir -p` parent dirs |
| `grep` | `subprocess.run(["grep", "-r", "-n", pattern, dir])` | Return matches with line numbers |
| `find_files` | `subprocess.run(["find", dir, "-name", pattern])` | Limit to 200 results |
| `list_dir` | `os.listdir(path)` with file sizes | Show dirs with `/` suffix |

**Critical from pi's design:** Tool errors must NOT raise Python exceptions. Return a descriptive error string and mark `is_error=True`. This lets Claude reason about what went wrong and try a different approach.

**Parallel execution:** Pi runs tool calls concurrently by default. Use `concurrent.futures.ThreadPoolExecutor` to execute all tool calls in a batch simultaneously, then collect results.

---

### Step 3 — `prompts.py`

Pi builds the system prompt dynamically. Key components from the actual source:

```python
import os
from datetime import date

def build_system_prompt(cwd: str | None = None, extra: str = "") -> str:
    cwd = cwd or os.getcwd()
    today = date.today().isoformat()

    return f"""You are an expert coding assistant running inside a terminal agent harness.
You help users by reading files, executing shell commands, editing code, and writing new files.

## Available Tools
- read_file: Read file contents, with optional line offset and limit
- bash: Execute shell commands (ls, git, grep, pytest, etc.)
- edit_file: Replace a specific string in a file with new content
- write_file: Create or overwrite a file with new content  
- grep: Search for text patterns across files
- find_files: Find files by name pattern
- list_dir: List directory contents

## Guidelines
- Start by understanding the task. Use read_file or list_dir to explore before making changes.
- Prefer targeted edits (edit_file) over full rewrites (write_file) for existing files.
- Always verify changes with bash (e.g., run tests, check syntax) after editing.
- When a tool returns an error, reason about it and try an alternative approach.
- Be concise in your text responses. Let the tools do the work.

## Environment
Working directory: {cwd}
Today's date: {today}

{extra}"""
```

---

### Step 4 — `provider.py`

LiteLLM replaces all of pi's `packages/ai/src/providers/` with a single function call. One async function: `stream_response()`.

```python
import litellm
from tools import TOOLS_SCHEMA

MODEL = "claude-sonnet-4-5"   # swap to "gemini/gemini-2.0-flash" or "gpt-4o" freely

async def stream_response(messages: list[dict], system_prompt: str):
    """
    Streams from any LiteLLM-supported provider.
    Yields OpenAI-compatible chunks regardless of the underlying model.
    """
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    response = await litellm.acompletion(
        model=MODEL,
        messages=full_messages,
        tools=TOOLS_SCHEMA,
        tool_choice="auto",
        max_tokens=8096,
        stream=True,
    )
    async for chunk in response:
        yield chunk
```

**Why async?** `litellm.acompletion` is non-blocking — the event loop can do other work (parallel tool execution) while waiting for tokens. Sync `litellm.completion` blocks the thread.

---

### Step 5 — `agent.py` (the core)

This is the while-loop. Mirror pi's nested outer/inner loop structure. Fully async.

```
Outer loop  →  handles follow-up messages ("steering") after agent would stop
Inner loop  →  the actual tool-call cycle
```

#### Streaming event accumulation (LiteLLM / OpenAI format)

LiteLLM normalizes all providers to OpenAI's chunk format. The structure is simpler than raw Anthropic events:

```
chunk.choices[0].delta.content          → text fragment (str | None)
chunk.choices[0].delta.tool_calls       → list of ToolCallChunk | None
  .index                                → which tool call this fragment belongs to
  .id                                   → tool call ID (only present on first chunk for that index)
  .function.name                        → tool name (only on first chunk)
  .function.arguments                   → partial JSON string fragment
chunk.choices[0].finish_reason          → "stop" | "tool_calls" | None
```

**Key difference from Anthropic raw events:** Tool call arguments arrive as a **partial JSON string** across multiple chunks. Buffer fragments by `index`, then `json.loads()` only after the stream ends (when `finish_reason` is set). Never parse mid-stream.

#### Full agent loop

```python
import asyncio
import json
from provider import stream_response
from prompts import build_system_prompt
from tools import TOOL_REGISTRY
from types_ import ToolResult

MAX_ITERATIONS = 30

async def run_agent(task: str) -> None:
    system_prompt = build_system_prompt()
    messages: list[dict] = [{"role": "user", "content": task}]
    pending_messages: list[dict] = []

    # OUTER LOOP: re-enter if follow-up messages arrive after agent finishes
    while True:
        has_more_tool_calls = True
        iteration = 0

        # INNER LOOP: tool-call cycle
        while (has_more_tool_calls or pending_messages) and iteration < MAX_ITERATIONS:
            iteration += 1

            if pending_messages:
                messages.extend(pending_messages)
                pending_messages.clear()

            # ── Phase A: Stream from LLM ──────────────────────────────────
            text_buf = ""
            # tool_acc: index → {id, name, arguments_buf}
            tool_acc: dict[int, dict] = {}
            finish_reason = None

            async for chunk in stream_response(messages, system_prompt):
                delta = chunk.choices[0].delta
                finish_reason = chunk.choices[0].finish_reason or finish_reason

                # Text fragment
                if delta.content:
                    text_buf += delta.content
                    print(delta.content, end="", flush=True)

                # Tool call fragments (may be multiple tool calls per turn)
                if delta.tool_calls:
                    for tc_chunk in delta.tool_calls:
                        idx = tc_chunk.index
                        if idx not in tool_acc:
                            tool_acc[idx] = {"id": "", "name": "", "arguments_buf": ""}
                        if tc_chunk.id:
                            tool_acc[idx]["id"] = tc_chunk.id
                        if tc_chunk.function and tc_chunk.function.name:
                            tool_acc[idx]["name"] = tc_chunk.function.name
                            print(f"\n▸ {tc_chunk.function.name}", end="", flush=True)
                        if tc_chunk.function and tc_chunk.function.arguments:
                            tool_acc[idx]["arguments_buf"] += tc_chunk.function.arguments

            print()  # newline after streamed text

            # Build finalized tool calls (parse JSON once, after stream ends)
            tool_calls = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments_buf"],  # keep as string for message history
                    },
                }
                for tc in tool_acc.values()
            ]

            # ── Phase B: Append assistant turn to history ─────────────────
            assistant_msg: dict = {"role": "assistant", "content": text_buf or None}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            # ── Phase C: Stop check ───────────────────────────────────────
            if finish_reason == "stop" or not tool_calls:
                has_more_tool_calls = False
                continue

            # ── Phase D: Execute tool calls in parallel ───────────────────
            parsed_calls = [
                {"id": tc["id"], "name": tc["function"]["name"],
                 "input": json.loads(tc["function"]["arguments"])}
                for tc in tool_calls
            ]
            results = await _execute_tools_parallel(parsed_calls)

            # ── Phase E: Push tool results — one "tool" message per result ─
            # OpenAI format: each tool result is its own message with role="tool"
            for r in results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": r.tool_call_id,
                    "content": r.content,
                })

        break  # no follow-up support in v1
```

#### Parallel tool execution (async)

```python
async def _execute_tools_parallel(tool_calls: list[dict]) -> list[ToolResult]:
    tasks = [_execute_one_tool(tc) for tc in tool_calls]
    return await asyncio.gather(*tasks)

async def _execute_one_tool(tool_call: dict) -> ToolResult:
    name = tool_call["name"]
    args = tool_call["input"]
    print(f"  [executing {name} {args}]")
    try:
        fn = TOOL_REGISTRY.get(name)
        if fn is None:
            return ToolResult(tool_call["id"], name, f"Unknown tool: {name}", is_error=True)
        # Tools are async; run blocking ones via asyncio.to_thread
        result = await fn(**args)
        print(f"  [✓ {name}: {len(result)} chars]")
        return ToolResult(tool_call["id"], name, result)
    except Exception as e:
        return ToolResult(tool_call["id"], name, str(e), is_error=True)
```

**Note on tool functions:** Declare tools as `async def`. For blocking I/O (file reads, subprocess), use `await asyncio.to_thread(blocking_fn, *args)` inside the tool so the event loop isn't blocked during tool execution.

---

### Step 6 — `main.py`

```python
import asyncio
import sys
from dotenv import load_dotenv
from agent import run_agent

async def main():
    load_dotenv()
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Task: ")
    await run_agent(task)

if __name__ == "__main__":
    asyncio.run(main())
```

Run with:
```bash
uv run main.py "add type hints to all functions in tools.py"
```

---

## LiteLLM + Async Gotchas

| Gotcha | Detail |
|--------|--------|
| Tool argument fragments arrive as partial JSON strings | Buffer `tc_chunk.function.arguments` by `index`; only `json.loads()` after stream ends |
| Multiple tool calls per turn | `delta.tool_calls` is a list; accumulate by `index`, not sequentially |
| `id` and `name` only appear on the first chunk for each tool call index | Always check `if tc_chunk.id` before overwriting — later chunks have `id=None` |
| Stop reason is `"tool_calls"`, not `"tool_use"` | LiteLLM uses OpenAI's `finish_reason` values |
| Tool results are `role: "tool"` messages, not packed into `role: "user"` | One `{"role": "tool", "tool_call_id": ..., "content": ...}` per result |
| Tool call `arguments` stays as a JSON string in message history | Don't convert to dict in the history — providers expect the string form |
| Blocking I/O in async tools blocks the event loop | Wrap with `await asyncio.to_thread(fn, *args)` for subprocess/file ops |
| `litellm.acompletion` needs `ANTHROPIC_API_KEY` in env | LiteLLM reads standard env vars per provider; no explicit client setup needed |
| Model string prefix selects the provider | `"claude-sonnet-4-5"` → Anthropic, `"gemini/gemini-2.0-flash"` → Google, `"gpt-4o"` → OpenAI |

---

## What To Skip in v1

| Feature | Where it lives in pi | Why skip |
|---------|----------------------|----------|
| Multi-provider support | `packages/ai/src/providers/` (40+ providers) | Already handled by LiteLLM — just change the model string |
| Terminal UI | `packages/tui/` | stdout is fine for learning |
| Memory / context compaction | `transformContext` hook | Add when you hit the 200k token limit |
| Steering messages (mid-run input) | `getSteeringMessages()` hook in pi | Non-trivial — needs async input handling |
| Extended thinking | `thinking` param in Anthropic provider | Nice to have, not essential |
| `beforeToolCall`/`afterToolCall` hooks | Agent loop hooks in pi | Add if you want permission prompts |
| Skills system | System prompt builder in pi | Just hardcode the system prompt for now |

---

## Build Order

1. `src/types_.py` — no dependencies; defines `ToolCall` and `ToolResult` dataclasses
2. `src/tools.py` — write + unit-test each tool in `tests/test_tools.py` before touching the loop
3. `src/prompts.py` — start as a plain string constant, make it dynamic (CWD, date) after
4. `src/provider.py` — call `litellm.acompletion` once, print raw chunks to understand the shape
5. `src/agent.py` — build the loop; wire streaming accumulation first, add parallel tool execution after
6. `main.py` — `asyncio.run(run_agent(task))`; test with `uv run main.py "list all .py files"`
7. `docs/architecture.md` — fill in after the loop works; explain the event flow and how to add a tool
8. `tests/test_agent.py` — mock `stream_response` to return canned chunks; test the loop logic

At each step, run something and see output before moving on.

```bash
# Install deps first
uv add litellm python-dotenv
```
