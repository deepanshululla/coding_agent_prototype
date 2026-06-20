---
sidebar_position: 1
title: System Prompts
description: How build_system_prompt() constructs a dynamic system prompt each run, embedding the working directory, today's date, and the tool list.
---

# System Prompts

The system prompt is the agent's standing instruction: it tells the model who it is, what tools it has, and how to behave. In this project, the prompt is not a hardcoded constant — it is built fresh on every run by `build_system_prompt()` in `src/prompts.py`.

:::note
`src/prompts.py` is implemented. The behavior described below reflects the shipped code.
:::

## Why build it dynamically?

A static string can't embed facts that change between runs:

- **Working directory** — the model needs to know where it's operating so it can interpret relative paths and produce correct `bash` commands.
- **Today's date** — without it, the model has no anchor for time-sensitive reasoning (e.g., picking a library version, understanding a log timestamp).
- **Tool list** — the prose description in the prompt must stay in sync with the actual `TOOL_REGISTRY`. If you add a tool, you update the registry and the prompt builder together; there is no separate "docs" file to drift.

Building at call time makes all three automatic.

## The function signature

```python
import os
from datetime import date

def build_system_prompt(cwd: str | None = None, extra: str = "") -> str:
    cwd = cwd or os.getcwd()
    today = date.today().isoformat()
    ...
```

`cwd` defaults to `os.getcwd()` so you get the right directory without passing anything. `extra` is a free-form string appended at the end — useful for per-task injections like a project-specific convention or a user-supplied instruction.

## The full prompt template

```python
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

## What each section does

| Section | Purpose |
|---------|---------|
| **Identity sentence** | Frames the model's role without over-constraining it. |
| **Available Tools** | Prose list that mirrors `TOOL_REGISTRY` exactly — seven tools, each with a one-line description. |
| **Guidelines** | Behavioral nudges derived from pi.dev's approach: explore before editing, prefer targeted edits, verify with tests, treat tool errors as information not exceptions. |
| **Environment** | Dynamic facts injected at call time: `cwd` and today's date as ISO-8601. |
| **extra** | Optional injection point — empty string by default, non-empty when a caller wants to add context. |

## Keeping the tool list in sync

The "Available Tools" section in the prompt is prose — it is not auto-generated from `TOOL_REGISTRY`. This means you have one consistency constraint to maintain: **every tool in `TOOL_REGISTRY` must appear in the prompt, and every tool named in the prompt must be in `TOOL_REGISTRY`**.

In practice this is straightforward because both live in the same codebase:

```
src/tools.py        ← defines TOOL_REGISTRY (name → async callable)
src/prompts.py      ← lists the same names in the "Available Tools" section
```

When you add a new tool, update both files. When you remove a tool, update both. The model will attempt to call tools by name; if a name appears in the prompt but not in `TOOL_REGISTRY`, the agent will return an "Unknown tool" error result back to the model.

:::tip
If you find yourself adding many tools and worrying about sync drift, consider generating the tool list from `TOOL_REGISTRY` at build time using the `description` field from each tool's JSON schema. That is a later refinement — for v1, manual sync is fine.
:::

## Where the prompt is consumed

`build_system_prompt()` is called once at the start of `run_agent()` in `src/agent.py`:

```python
system_prompt = build_system_prompt()
messages: list[dict] = [{"role": "user", "content": task}]
```

The prompt is then prepended to every `litellm.acompletion` call inside `stream_response()`:

```python
full_messages = [{"role": "system", "content": system_prompt}] + messages
```

It does not change during a session. The `messages` list grows; the system prompt stays fixed.

## Customizing the prompt

See [Prompt Templates](../customization/prompt-templates.md) for how to inject per-project conventions, override the guidelines section, or structure multi-role prompts for specialized agents.
