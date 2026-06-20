---
sidebar_position: 2
title: "tools.py"
description: The 7 async tool functions, TOOLS_SCHEMA, and TOOL_REGISTRY that the agent can invoke.
---

# tools.py

`src/tools.py` defines everything the agent can do: seven async functions that read files, run shell commands, search for patterns, and write or edit code. Each tool has a JSON schema that gets passed to the LLM so it knows what tools are available and how to call them. See [built-in tools](../tools/overview.md) for a user-facing overview of what each tool does.

:::note
The signatures and behavior described here reflect the shipped `src/tools.py`.
:::

---

## Module-level objects

### `TOOLS_SCHEMA`

```python
TOOLS_SCHEMA: list[dict]
```

A list of OpenAI-style tool schema dicts, one per tool. Passed verbatim to `litellm.acompletion(tools=TOOLS_SCHEMA)`. LiteLLM translates these to whatever format the underlying provider expects.

Each entry follows this shape:

```json
{
  "type": "function",
  "function": {
    "name": "read_file",
    "description": "Read the contents of a file. Use offset/limit for large files.",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {"type": "string", "description": "File path to read"},
        "offset": {"type": "integer", "description": "Line to start from (0-indexed)", "default": 0},
        "limit": {"type": "integer", "description": "Max lines to return", "default": 2000}
      },
      "required": ["path"]
    }
  }
}
```

:::tip
The key is `"parameters"`, not `"input_schema"`. LiteLLM uses OpenAI's format; the underlying Anthropic provider sees `input_schema` only after LiteLLM translates it internally.
:::

---

### `TOOL_REGISTRY`

```python
TOOL_REGISTRY: dict[str, callable]
```

Maps tool names (strings) to their async callable implementations. The agent loop looks up tool names here at runtime.

```python
TOOL_REGISTRY = {
    "read_file":   read_file,
    "bash":        bash,
    "edit_file":   edit_file,
    "write_file":  write_file,
    "grep":        grep,
    "find_files":  find_files,
    "list_dir":    list_dir,
}
```

---

## Tool functions

All tool functions are `async def`. Blocking I/O (file reads, subprocess calls) is wrapped with `await asyncio.to_thread(...)` so the event loop is not blocked during parallel tool execution.

**Error contract:** Tool functions never raise. On failure, they return a descriptive error string. The agent loop sets `is_error=True` on the resulting `ToolResult`, which lets the model reason about what went wrong and try a different approach.

---

### `read_file`

```python
async def read_file(path: str, offset: int = 0, limit: int = 2000) -> str
```

Reads a file from disk, optionally slicing a range of lines. Useful for large files where you only need a section.

**Parameters**

| Parameter | Type  | Default | Description                                       |
|-----------|-------|---------|---------------------------------------------------|
| `path`    | `str` | —       | Absolute or relative path to the file to read.    |
| `offset`  | `int` | `0`     | Zero-indexed line number to start reading from.   |
| `limit`   | `int` | `2000`  | Maximum number of lines to return.                |

**Returns** The file contents as a string. If `offset` or `limit` are applied, only the selected range is returned.

**Error behavior** Returns an error string (e.g., `"Error: file not found: /path/to/file"`) on `FileNotFoundError` or permission errors.

```python
# Read first 50 lines of a file
result = await read_file("src/agent.py", offset=0, limit=50)
```

---

### `bash`

```python
async def bash(command: str) -> str
```

Runs a shell command and returns its combined stdout and stderr, along with the exit code.

**Parameters**

| Parameter | Type  | Default | Description                                        |
|-----------|-------|---------|----------------------------------------------------|
| `command` | `str` | —       | Shell command to execute. Runs with `shell=True`.  |

**Returns** A string containing stdout, stderr, and the exit code in the form `(exit code N)\n<output>`. Output is truncated to `BASH_OUTPUT_LIMIT` (10,000 characters) to prevent flooding the context window. The timeout is controlled by `BASH_TIMEOUT` (30 seconds), a module-level constant in `src/tools.py`.

**Error behavior** Returns the error output and exit code rather than raising. A non-zero exit code is included in the returned string so the model can detect failure.

```python
# Run tests and capture output
result = await bash("cd /project && python -m pytest tests/ -v")
```

---

### `edit_file`

```python
async def edit_file(path: str, old_string: str, new_string: str) -> str
```

Performs a targeted find-and-replace within an existing file. The replacement is applied only if `old_string` appears exactly once in the file.

**Parameters**

| Parameter    | Type  | Description                                                     |
|--------------|-------|-----------------------------------------------------------------|
| `path`       | `str` | Path to the file to edit.                                       |
| `old_string` | `str` | Exact string to find in the file (must match exactly once).     |
| `new_string` | `str` | Replacement string.                                             |

**Returns** A success message indicating the file was updated.

**Error behavior** Returns an error string if:
- The file does not exist
- `old_string` is not found in the file
- `old_string` appears more than once (ambiguous edit)

```python
# Replace a function signature
result = await edit_file(
    "src/agent.py",
    "async def run_agent(task):",
    "async def run_agent(task: str) -> None:",
)
```

---

### `write_file`

```python
async def write_file(path: str, content: str) -> str
```

Creates or fully overwrites a file with the given content. Parent directories are created if they do not exist.

**Parameters**

| Parameter | Type  | Description                                       |
|-----------|-------|---------------------------------------------------|
| `path`    | `str` | Path to the file to create or overwrite.          |
| `content` | `str` | Full content to write.                            |

**Returns** A success message with the file path.

**Error behavior** Returns an error string on permission errors or path issues.

```python
result = await write_file("src/config.py", "DEBUG = False\nVERSION = '1.0.0'\n")
```

:::tip
Prefer `edit_file` for modifying existing files. `write_file` on an existing file discards all content not present in `content`.
:::

---

### `grep`

```python
async def grep(pattern: str, path: str = ".") -> str
```

Searches recursively for a text pattern across files, returning matching lines with file paths and line numbers. Always uses `grep -r -n` (recursive, with line numbers).

**Parameters**

| Parameter | Type  | Default | Description                                      |
|-----------|-------|---------|--------------------------------------------------|
| `pattern` | `str` | —       | The pattern to search for (passed to `grep -r -n`). |
| `path`    | `str` | `"."`   | Directory or file to search in.                  |

**Returns** Newline-separated matches in the format `filepath:lineno:line`. Returns a "No matches" message when `grep` exits with code 1.

**Error behavior** Returns a "No matches" message when nothing is found; returns an error string if grep itself fails.

```python
result = await grep("async def", "src/")
```

---

### `find_files`

```python
async def find_files(pattern: str, path: str = ".") -> str
```

Finds files by name pattern (glob-style) under a directory. Results are capped at `FIND_LIMIT` (200 entries).

**Parameters**

| Parameter | Type  | Default | Description                                            |
|-----------|-------|---------|--------------------------------------------------------|
| `pattern` | `str` | —       | Filename pattern (e.g., `"*.py"`, `"test_*.py"`).     |
| `path`    | `str` | `"."`   | Root directory to search from.                         |

**Returns** Newline-separated list of matching file paths, up to 200 results. Appends a `... [N more]` note if results were clipped.

**Error behavior** Returns a "No files matching" message if nothing is found; returns an error string if `find` itself fails.

```python
result = await find_files("*.py", "src/")
```

---

### `list_dir`

```python
async def list_dir(path: str = ".") -> str
```

Lists the contents of a directory, showing file sizes and distinguishing directories with a trailing `/`.

**Parameters**

| Parameter | Type  | Default | Description                         |
|-----------|-------|---------|-------------------------------------|
| `path`    | `str` | `"."`   | Directory path to list.             |

**Returns** A formatted string with one entry per line: name (directories suffixed with `/`), type, and size in bytes.

**Error behavior** Returns an error string if the path does not exist or is not a directory.

```python
result = await list_dir("src/")
# → "agent.py  (file, 3421 bytes)\ntools.py  (file, 5102 bytes)\n..."
```

---

## Related pages

- [Built-in tools](../tools/overview.md) — user-facing description of each tool's purpose
- [Tool schema format](../tools/schema-format.md) — details on the OpenAI-style schema
- [agent.py](./agent.md) — how `TOOL_REGISTRY` is used in the loop
- [types_.py](./types.md) — `ToolResult` that wraps each tool's output
