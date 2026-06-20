---
sidebar_position: 15
title: Troubleshooting
description: Symptom-to-fix table for the most common LiteLLM, async, and message-format errors.
---

# Troubleshooting

Symptom-to-fix guide for the gotchas described in `PLAN.md`. Most of these stem from three sources: streaming chunk accumulation, the OpenAI message format that LiteLLM uses, and async I/O requirements.

---

## Streaming and chunk accumulation

### JSON parse error when reading tool call arguments mid-stream

**Symptom:** `json.JSONDecodeError` (or a truncated/invalid dict) when you try to use tool arguments.

**Cause:** Tool call arguments arrive as a partial JSON string split across multiple streaming chunks. If you call `json.loads()` on a fragment before the stream ends, you get a broken string.

**Fix:** Buffer `tc_chunk.function.arguments` by `index` across all chunks. Only call `json.loads()` once, after the stream ends (when `finish_reason` is set):

```python
# During streaming: accumulate
tool_acc[idx]["arguments_buf"] += tc_chunk.function.arguments

# After stream ends: parse once
input = json.loads(tc["arguments_buf"])
```

See [The agent loop](./architecture/the-agent-loop.md) for the full buffering pattern.

---

### Tool call `id` or `name` gets overwritten with `None`

**Symptom:** `tool_call["id"]` or `tool_call["name"]` ends up `None` or empty after streaming.

**Cause:** The `id` and `name` fields only appear on the *first* chunk for each tool call index. Later chunks for the same tool call have `id=None` and `function.name=None`. If you unconditionally assign them, later chunks overwrite the real values with `None`.

**Fix:** Guard before assigning:

```python
if tc_chunk.id:
    tool_acc[idx]["id"] = tc_chunk.id
if tc_chunk.function and tc_chunk.function.name:
    tool_acc[idx]["name"] = tc_chunk.function.name
```

---

### Multiple tool calls are confused or interleaved

**Symptom:** Tool arguments from two different tool calls end up merged, or one call has an empty name.

**Cause:** When the model requests multiple tool calls in one turn, `delta.tool_calls` is a list with items at different indices. If you append arguments without tracking `index`, you mix up calls.

**Fix:** Accumulate by `index`, not sequentially:

```python
for tc_chunk in delta.tool_calls:
    idx = tc_chunk.index          # which tool call this fragment belongs to
    if idx not in tool_acc:
        tool_acc[idx] = {"id": "", "name": "", "arguments_buf": ""}
    # ... accumulate into tool_acc[idx]
```

---

## Stop reason and loop control

### The inner loop never stops even when the model is done

**Symptom:** The agent keeps looping after the model has finished responding, or it hits `MAX_ITERATIONS` on a simple task.

**Cause:** Checking for `finish_reason == "tool_use"` (Anthropic raw format) instead of `"tool_calls"` (LiteLLM/OpenAI format). LiteLLM normalizes the finish reason to OpenAI's value.

**Fix:** Check for `"tool_calls"`, not `"tool_use"`:

```python
if finish_reason == "stop" or not tool_calls:
    has_more_tool_calls = False
    continue
```

If `finish_reason == "tool_calls"`, there are tool calls to execute and the loop should continue.

---

## Message history format

### Model returns an error about tool results not being associated with a tool call

**Symptom:** API error: something like "tool results must follow an assistant turn with tool_calls" or "unexpected role".

**Cause:** Tool results are being packed into a `role: "user"` message (as in the raw Anthropic SDK format) instead of individual `role: "tool"` messages (the OpenAI/LiteLLM format).

**Fix:** Each tool result gets its own message with `role: "tool"`:

```python
for r in results:
    messages.append({
        "role": "tool",
        "tool_call_id": r.tool_call_id,
        "content": r.content,
    })
```

Do not pack multiple results into one `role: "user"` message with a list of blocks. LiteLLM expects the OpenAI format.

---

### Tool call arguments stored as a dict cause an error on the next API call

**Symptom:** API error or validation failure on the second or later API call, but the first call worked fine.

**Cause:** Tool call `arguments` must stay as a JSON *string* in the message history, not a parsed dict. If you convert them to a dict when appending the assistant message, providers will reject it.

**Fix:** Keep the arguments as a string when building the assistant message:

```python
assistant_msg["tool_calls"] = [
    {
        "id": tc["id"],
        "type": "function",
        "function": {
            "name": tc["name"],
            "arguments": tc["arguments_buf"],   # string, not dict
        },
    }
    for tc in tool_acc.values()
]
```

Parse the string to a dict only when you actually need to call the Python function:

```python
input = json.loads(tc["function"]["arguments"])
result = await fn(**input)
```

---

## Async and blocking I/O

### The event loop freezes during tool execution

**Symptom:** The agent hangs for several seconds during a `bash` or `read_file` call. Parallel tool calls run sequentially instead of concurrently.

**Cause:** A tool function uses `subprocess.run(...)` or `Path.read_text()` inside a plain synchronous code path inside an `async def`. This blocks the entire event loop thread.

**Fix:** Wrap blocking I/O with `await asyncio.to_thread(...)`:

```python
async def bash(cmd: str, timeout: int = 30) -> str:
    def _run():
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return (result.stdout + result.stderr)[:10_000]
    return await asyncio.to_thread(_run)
```

`asyncio.to_thread` runs the blocking function in a thread pool, freeing the event loop to handle other coroutines — including the other tool calls running via `asyncio.gather`.

---

## Environment and configuration

### `litellm.acompletion` raises an authentication error

**Symptom:** `AuthenticationError`, `401`, or "No API key provided" from LiteLLM.

**Cause:** `ANTHROPIC_API_KEY` (or the relevant provider's key) is not set in the environment. LiteLLM reads standard environment variable names automatically — there is no explicit client setup needed — but the variable must be present.

**Fix:** Make sure `.env` exists at the project root with the key:

```
ANTHROPIC_API_KEY=sk-ant-...
```

And that `main.py` calls `load_dotenv()` before the first `await run_agent(...)`:

```python
from dotenv import load_dotenv
load_dotenv()
```

---

### LiteLLM picks the wrong provider

**Symptom:** Sending to OpenAI when you expected Anthropic, or a "model not found" error.

**Cause:** The model string prefix determines the provider. If the prefix is missing or wrong, LiteLLM uses the wrong provider.

**Fix:** Use the exact format for the provider you want:

| Provider | Model string format | Example |
|----------|--------------------|----|
| Anthropic | `<model-name>` (no prefix) | `"claude-sonnet-4-5"` |
| Google | `gemini/<model-name>` | `"gemini/gemini-2.0-flash"` |
| OpenAI | `<model-name>` (no prefix) | `"gpt-4o"` |
| Ollama | `ollama/<model-name>` | `"ollama/llama3"` |

---

## Import errors

### `ModuleNotFoundError: No module named 'agent'` (or `tools`, `types_`, etc.)

**Symptom:** Import error when running tests or `main.py`.

**Cause:** `src/` is not a package and is not on `sys.path` by default.

**Fix — for tests:** Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
```

**Fix — for `main.py`:** Add at the top, before any `src` imports:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
```

Do not add `__init__.py` to `src/` to fix this — it would change the import semantics and is intentionally absent.

---

## Related pages

- [FAQ](./faq.md) — why the design decisions were made this way
- [The agent loop](./architecture/the-agent-loop.md) — full streaming and accumulation walkthrough
- [Project Conventions](./contributing/project-conventions.md) — async requirements, schema format
