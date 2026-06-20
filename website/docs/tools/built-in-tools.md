---
sidebar_position: 3
title: Built-in Tools
description: Reference for all 7 built-in tools — parameters, implementation approach, and error behaviour.
---

# Built-in Tools

The agent ships with 7 tools covering the operations a coding agent needs most: reading and writing files, running shell commands, and searching the codebase. This page is the reference for each one.

:::note
These tools are implemented in `src/tools.py`. The behaviour described here matches the shipped code.
:::

## Summary table

| Tool | One-line purpose | Key constraint |
|---|---|---|
| `read_file` | Read file contents with optional pagination | Returns error string on any I/O failure |
| `write_file` | Create or overwrite a file | Creates parent directories automatically |
| `edit_file` | Replace an exact string in an existing file | Errors if `old_string` not found or not unique |
| `bash` | Run any shell command | 30 s timeout; output truncated to 10 000 chars |
| `grep` | Search for a regex pattern across files | Returns matches with line numbers |
| `find_files` | Find files by name glob | Results capped at 200 |
| `list_dir` | List directory contents | Dirs shown with trailing `/` |

---

## `read_file`

**Purpose:** Read the text content of a file. Supports line-based pagination for large files so the model isn't forced to load a 10 000-line codebase into a single tool result.

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | yes | — | Path to the file to read |
| `offset` | integer | no | `0` | Line to start reading from (0-indexed) |
| `limit` | integer | no | `2000` | Maximum number of lines to return |

**Implementation:** `Path(path).read_text()` followed by line slicing using `offset` and `limit`. The result includes the raw text of those lines.

**On error:** Returns a descriptive error string (e.g., `"File not found: /path/to/file"`) and sets `is_error=True`. Never raises.

---

## `write_file`

**Purpose:** Create a new file or completely overwrite an existing one with the provided content. Use for new files or when the model wants to replace a file wholesale. Prefer `edit_file` for targeted changes to existing files.

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | yes | — | Destination file path |
| `content` | string | yes | — | Full content to write |

**Implementation:** `Path(path).write_text(content)` after calling `Path(path).parent.mkdir(parents=True, exist_ok=True)` to create any missing parent directories. This means you can write to a deeply nested path that doesn't exist yet.

**On error:** Returns an error string if the path is unwritable or another I/O error occurs.

---

## `edit_file`

**Purpose:** Replace a specific substring in an existing file. Designed for surgical edits — change one function, update one line — without rewriting the whole file.

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | yes | — | Path to the file to edit |
| `old_string` | string | yes | — | Exact text to find and replace |
| `new_string` | string | yes | — | Text to substitute in its place |

**Implementation:** Reads the file, finds `old_string`, replaces it with `new_string`, and writes back. The match is exact — whitespace and indentation must match the file exactly.

**Error cases:**
- `old_string` not found in the file → returns an error string. The model can then read the file and retry with the correct text.
- `old_string` appears more than once → returns an error string, because the tool cannot determine which occurrence to replace. Make `old_string` longer (include more surrounding context) to make it unique.

:::warning
`edit_file` requires an exact match. If the model constructs `old_string` from memory rather than reading the file first, it will often be wrong. The correct pattern is: `read_file` → observe the exact text → `edit_file`.
:::

---

## `bash`

**Purpose:** Execute any shell command and return its combined stdout, stderr, and exit code. The workhorse tool for running tests, inspecting git state, installing packages, or any other operation the dedicated tools don't cover.

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `command` | string | yes | — | Shell command to execute |

**Implementation:** `subprocess.run(command, shell=True, capture_output=True, timeout=30)`. The `shell=True` flag means you can use pipes, redirects, and shell built-ins (`cd`, `&&`, etc.) in the command string.

**Output handling:**
- stdout and stderr are combined and returned as a single string.
- Output is truncated to **10 000 characters** to avoid flooding the model's context window. If truncated, a notice is appended.
- The exit code is appended to the output so the model can distinguish success from failure even when stderr is empty.

**On timeout:** Returns an error string noting the 30-second limit was exceeded. Long-running commands (builds, tests with many files) may need to be split or given explicit time limits.

**On error:** Non-zero exit codes are returned as content, not as Python exceptions. The model reads the exit code and stderr and reasons about what went wrong.

```
stdout: <output here, truncated to 10k>
exit_code: 1
```

---

## `grep`

**Purpose:** Search for a text pattern across one or more files and return matching lines with file paths and line numbers. Useful for locating definitions, usages, or any string across a directory tree.

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `pattern` | string | yes | — | Pattern to search for |
| `path` | string | no | `.` | Directory or file to search under |

**Implementation:** `subprocess.run(["grep", "-r", "-n", pattern, path])`. The `-r` flag searches recursively; `-n` includes line numbers. Results come back in the standard `path:lineno:content` format.

**On error:** Returns an error string if `grep` itself fails (e.g., invalid regex, unreadable directory).

---

## `find_files`

**Purpose:** Find files whose names match a glob pattern, recursively from a starting directory. Use it to locate files when you know the name pattern but not the path.

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `pattern` | string | yes | — | Filename glob (e.g., `*.py`, `test_*.py`) |
| `path` | string | no | `.` | Directory to search under |

**Implementation:** `subprocess.run(["find", path, "-name", pattern])`. Results are limited to **200 entries** (`FIND_LIMIT`) to prevent runaway output in large repositories. If the actual count exceeds 200, only the first 200 are returned with a note.

**On error:** Returns an error string if `find` fails or the directory doesn't exist.

---

## `list_dir`

**Purpose:** List the contents of a directory with file sizes and a visual marker for subdirectories. Use it to orient yourself before diving into reads or searches.

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | no | `.` | Directory path to list |

**Implementation:** `os.listdir(path)` combined with `os.stat` for file sizes. Subdirectories are shown with a trailing `/` so the model can immediately distinguish them from files.

**On error:** Returns an error string if the path doesn't exist or is not a directory.

---

## Common patterns

**Explore then edit:**
```
list_dir(".") → read_file("src/tools.py") → edit_file("src/tools.py", ...)
```

**Find then verify:**
```
find_files("*.py", "tests/") → bash("python -m pytest tests/test_tools.py -v")
```

**Search then read context:**
```
grep("def read_file", "src/") → read_file("src/tools.py", offset=10, limit=40)
```

## Related pages

- [Schema Format](./schema-format.md) — how to read the schema for each tool
- [Parallel Execution](./parallel-execution.md) — all 7 can run concurrently in one turn
- [Error Handling](./error-handling.md) — why every tool returns errors instead of raising
- [Adding a Tool](./adding-a-tool.md) — add an eighth tool following the same pattern
