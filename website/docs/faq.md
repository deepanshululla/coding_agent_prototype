---
sidebar_position: 14
title: FAQ
description: Frequently asked questions about design decisions, configuration, and how the agent works.
---

# FAQ

Common questions about why the project is built the way it is, and what it does and doesn't do.

---

## Why LiteLLM instead of the raw Anthropic SDK?

The raw Anthropic SDK only works with Anthropic models. LiteLLM is a thin adapter layer that normalizes every provider's response to OpenAI's format. You write the streaming loop once and swap models by changing a single string:

```python
MODEL = "claude-sonnet-4-5"       # Anthropic
MODEL = "gemini/gemini-2.0-flash" # Google
MODEL = "gpt-4o"                  # OpenAI
```

Pi.dev (the project this is modeled on) achieves the same thing through a hand-rolled `packages/ai/` abstraction with 40+ provider adapters. LiteLLM gives us the same capability in zero code. The tradeoff is a dependency; the benefit is not having to maintain provider-specific streaming parsers.

---

## Why async?

Two reasons:

1. `litellm.acompletion` is non-blocking. The event loop can do other work — specifically, run multiple tool calls in parallel — while waiting for the next token from the API.
2. Tool calls execute in parallel via `asyncio.gather`. If the model asks for three tool calls in one turn, they all start simultaneously. With synchronous code you'd run them sequentially.

Using `litellm.completion` (the sync version) instead would block the thread for the entire duration of each API call, making parallel tool execution impossible and freezing the process while waiting for tokens.

---

## Why do tool errors return strings instead of raising exceptions?

If a tool raises a Python exception, the agent loop crashes. If a tool returns a descriptive error string with `is_error=True`, the model reads the error, reasons about what went wrong, and tries a different approach.

That recovery behavior is the point of the agent loop. Exceptions short-circuit it. Every tool function catches its own errors and returns them as strings:

```python
except FileNotFoundError:
    return f"Error: file not found: {path}"
```

See [Project Conventions](./contributing/project-conventions.md#tools-never-raise-exceptions) for more.

---

## Why is the module named `types_` with a trailing underscore?

Python's standard library already has a module called `types`. Naming our file `types.py` would shadow it across the entire process, causing subtle import errors in stdlib code that does `import types` internally.

The trailing underscore is the conventional fix for name collisions with builtins and stdlib modules. One character avoids a hard-to-diagnose bug.

---

## Why OpenAI schema format for tools, not Anthropic's `input_schema`?

LiteLLM normalizes everything to OpenAI's format and translates internally to whatever the provider needs. If you pass Anthropic-style schemas (with `input_schema`) to `litellm.acompletion`, LiteLLM will not handle them correctly.

Write schemas once in OpenAI format — `type: "function"` wrapper, `parameters` key — and they work across all providers:

```python
{
    "type": "function",
    "function": {
        "name": "read_file",
        "parameters": { ... }   # not "input_schema"
    }
}
```

See [Tools schema format](./tools/schema-format.md) for the full reference.

---

## How do I change the model?

Edit the `MODEL` constant at the top of `src/provider.py`:

```python
MODEL = "claude-sonnet-4-5"        # default
# MODEL = "gemini/gemini-2.0-flash"
# MODEL = "gpt-4o"
```

Make sure the corresponding API key is set in `.env`. LiteLLM reads standard environment variable names per provider: `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_KEY`.

No other code changes are required — the streaming loop, tool schema format, and message history format are provider-agnostic through LiteLLM.

---

## Is there a UI?

No. This project is stdout-only. Text and tool-execution status print to the terminal as the agent runs. There is no TUI (terminal UI), web interface, or interactive prompt between tool calls.

Pi.dev (the inspiration) has a full TUI in `packages/tui/`. That's intentionally out of scope here — see [Differences from pi.dev](./differences-from-pi.md) for the full list of what's included vs. what's not.

---

## What's the difference between the inner loop and the outer loop?

The **inner loop** is the core agent cycle: send messages to the model, stream the response, if the model requested tool calls then execute them in parallel and push the results back, repeat until the model stops requesting tools or `MAX_ITERATIONS` (30) is reached.

The **outer loop** handles follow-up messages — "steering" input that arrives after the agent would otherwise stop. In v1, the outer loop is a single iteration (it `break`s unconditionally after the inner loop finishes). The structure is in place for future follow-up support but it doesn't do anything yet.

```
Outer loop  →  re-enter if follow-up messages arrive after agent finishes
  Inner loop  →  the actual tool-call cycle (stream → tools → results → repeat)
```

See [The agent loop](./architecture/the-agent-loop.md) for a detailed walkthrough.

---

## Is the conversation persisted between runs?

No. Each `uv run main.py "..."` invocation starts a fresh conversation. The `messages` list is built in memory during the run and discarded when the process exits.

Context compaction (managing the conversation when it approaches the model's token limit) and persistence are both listed as post-v1 features. See [Differences from pi.dev](./differences-from-pi.md) for the full roadmap of what's planned but not yet implemented.

---

## What is MAX_ITERATIONS and can I change it?

`MAX_ITERATIONS = 30` is a hard cap on how many inner-loop iterations the agent will run before stopping, regardless of whether it's still making tool calls. It prevents runaway loops.

You can change it by editing `src/agent.py`. There is no CLI flag or config file for it in v1. Thirty iterations is generous for most tasks; lower it if you want stricter budgeting.

---

## Can I use this with a local model (Ollama, etc.)?

LiteLLM supports Ollama and other local inference servers. Set the model string to the appropriate LiteLLM provider prefix and make sure the server is running:

```python
MODEL = "ollama/llama3"  # example
```

No `ANTHROPIC_API_KEY` is needed for local models. Check the [LiteLLM docs](https://docs.litellm.ai/docs/providers) for the exact model string format per provider. No other changes to this project are required.

---

## Related pages

- [Troubleshooting](./troubleshooting.md) — symptom-to-fix table for common errors
- [Differences from pi.dev](./differences-from-pi.md) — what's in scope vs. what's intentionally out
- [Getting started](./getting-started/quickstart.md) — installation and first run
