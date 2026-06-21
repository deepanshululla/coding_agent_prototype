from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import litellm

import renderer
from config import MAX_TOKENS, MODEL, THINKING_BUDGET, VLM_MODEL
from tools import TOOLS_SCHEMA

# Extended thinking (Phase 17) is only supported by some Claude models. We gate
# on a substring rather than an exact id so provider-prefixed aliases (e.g.
# "anthropic/claude-sonnet-4-5", "bedrock/...claude-sonnet-4...") still match.
_THINKING_MODEL_MARKERS = ("claude-sonnet-4", "claude-opus-4", "claude-3-7")


def _supports_thinking(model: str) -> bool:
    """True if `model` is a Claude variant known to support extended thinking.

    Conservative: only flips on for the marker families above. An unknown or
    non-Claude model returns False so we never send a `thinking` param the
    backend would reject.
    """
    m = (model or "").lower()
    return any(marker in m for marker in _THINKING_MODEL_MARKERS)


def _thinking_kwargs(model: str) -> dict:
    """Build the litellm kwargs for extended thinking, or {} when disabled.

    Returns the `thinking` param plus a bumped `max_tokens` only when
    THINKING_BUDGET > 0 AND the model supports it. max_tokens must exceed
    budget_tokens (the model needs room to answer after reasoning), so we floor
    it at budget + 2000 and never below the configured MAX_TOKENS. When thinking
    is off we still pass MAX_TOKENS so the call shape is otherwise unchanged.
    """
    if THINKING_BUDGET > 0 and _supports_thinking(model):
        max_tokens = max(MAX_TOKENS, THINKING_BUDGET + 2000)
        # Guard against misconfiguration — the API rejects budget >= max_tokens.
        assert max_tokens > THINKING_BUDGET, (
            f"max_tokens ({max_tokens}) must exceed THINKING_BUDGET ({THINKING_BUDGET})"
        )
        return {
            "thinking": {"type": "enabled", "budget_tokens": THINKING_BUDGET},
            "max_tokens": max_tokens,
        }
    return {"max_tokens": MAX_TOKENS}


# Phase 13.6: an opt-in fork that shells out to `claude -p` instead of LiteLLM.
# Set USE_CLAUDE_CLI_LLM=1 to route stream_response through the local Claude CLI
# (text-only — TOOLS_SCHEMA is not forwarded). Any other value keeps the LiteLLM
# path. MODEL / MAX_TOKENS are read from the environment via config (AGENT_MODEL,
# AGENT_MAX_TOKENS), so the provider is configurable without touching this file.
USE_CLAUDE_CLI = os.environ.get("USE_CLAUDE_CLI_LLM", "") == "1"

# Permission mode for the `claude -p` subprocess. In print mode the CLI cannot
# show an interactive approval prompt, so without a permission mode every write
# and bash call is denied ("I need permission..."). Default to bypassPermissions
# to mirror this project's own default posture (AGENT_PERMISSION_MODE=auto);
# override with CLAUDE_CLI_PERMISSION_MODE (e.g. acceptEdits) for a stricter run.
CLI_PERMISSION_MODE = os.environ.get("CLAUDE_CLI_PERMISSION_MODE", "bypassPermissions")

# Max bytes a single `claude -p` stream-json NDJSON line may reach before the
# asyncio StreamReader errors. The default (64KB) overflows on image turns — the
# CLI echoes the read image as a base64 block on one line — so we raise it to
# 64MB, comfortably above a base64-expanded 5MB image (IMAGE_MAX_BYTES) plus the
# surrounding JSON. It is a ceiling, not a preallocation.
_CLI_STREAM_LIMIT = 64 * 1024 * 1024


def _chunk(
    content=None, finish_reason=None, tool_calls=None, thinking=None, signature=None, usage=None
):
    """Build one OpenAI-format streaming chunk the agent loop understands.

    Uses SimpleNamespace so no provider SDK is needed in tests. litellm yields
    real chunk objects with this same shape, so the loop — and the test harness
    that scripts these chunks — sees one interface regardless of backend.
    tool_calls carries a list of streamed tool-call fragments, each shaped like
    _tc() below.

    thinking / signature (Phase 17) carry an extended-thinking delta. litellm
    surfaces the reasoning stream as `delta.thinking` and the verification
    signature as `delta.thinking_blocks[...].signature`; we expose both on the
    delta so scripted chunks can drive the agent's thinking accumulator. When
    thinking is None the delta is shaped exactly as before, so non-thinking
    callers and the existing tests are unaffected.
    """
    delta = SimpleNamespace(content=content, tool_calls=tool_calls, thinking=thinking)
    if signature is not None:
        delta.signature = signature
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    # usage rides on the chunk (litellm puts it on the final chunk when
    # stream_options.include_usage is set; the CLI fork synthesizes it from the
    # stream-json result event). None on every other chunk.
    return SimpleNamespace(choices=[choice], usage=usage)


def _tc(index, id=None, name=None, arguments=None):
    """Build one OpenAI-format tool-call delta fragment for a streaming chunk.

    Mirrors the shape litellm yields in delta.tool_calls: an .index, an .id,
    and a nested .function with .name and .arguments. A whole call may arrive in
    one fragment, or .arguments may be split across fragments.
    """
    function = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=id, function=function)


def _parse_image_payload(content: object) -> tuple[str, str] | None:
    """Return (format, base64) if `content` is a read_file image result, else None.

    `read_file` returns images as the JSON string
    {"type":"image","format":"png","data":"<base64>"} (tools.py). A normal text
    tool result is left alone by the cheap substring guard before we json.loads,
    so this is effectively free on the common (text) path.
    """
    if not isinstance(content, str) or '"image"' not in content:
        return None
    try:
        obj = json.loads(content)
    except (ValueError, TypeError):
        return None
    if (
        isinstance(obj, dict)
        and obj.get("type") == "image"
        and obj.get("format")
        and obj.get("data")
    ):
        return obj["format"], obj["data"]
    return None


def _lift_tool_image_results(messages: list[dict]) -> list[dict]:
    """Lift image tool-results into a real multimodal `user` message.

    A `role:"tool"` message is plain text to every provider, so the base64 an
    image read returns is invisible to the model. We replace that base64 with a
    short text placeholder and re-attach the image as an `image_url` block on a
    `user` message that follows the tool batch — the provider-agnostic shape
    (OpenAI/Anthropic/Ollama all accept image_url in user content).

    All images from one contiguous tool batch are collected into a single trailing
    user message so the tool_result grouping providers require (every result for
    an assistant's tool_use before the next user turn) is preserved. Non-image
    tool results and the input list itself are untouched (a fresh list is built).
    """
    out: list[dict] = []
    pending: list[dict] = []

    def _flush() -> None:
        if pending:
            out.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Image(s) read by the read_file tool:"},
                        *pending,
                    ],
                }
            )
            pending.clear()

    for msg in messages:
        if msg.get("role") == "tool":
            img = _parse_image_payload(msg.get("content"))
            if img is not None:
                fmt, data = img
                placeholder = f"[image read ({fmt}); attached in the next message]"
                out.append({**msg, "content": placeholder})
                pending.append(
                    {"type": "image_url", "image_url": {"url": f"data:image/{fmt};base64,{data}"}}
                )
                continue
        else:
            # A non-tool message closes the current tool batch; flush its images
            # first so they land right after the batch and before this message.
            _flush()
        out.append(msg)

    _flush()
    return out


def _contains_image(messages: list[dict]) -> bool:
    """True if any message carries a multimodal image_url block.

    Used to decide vision routing. Run on the lifted messages so it catches both
    pasted user images and images lifted out of tool results.
    """
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "image_url" for b in content
        ):
            return True
    return False


async def stream_response(
    messages: list[dict], system_prompt: str, model: str | None = None
) -> AsyncIterator[Any]:
    """Stream a model response as OpenAI-format chunks.

    acompletion is non-blocking, so the event loop stays free to execute tools
    concurrently while tokens arrive. Yields chunks unchanged for the agent loop
    to accumulate. The backend is LiteLLM (Phase 11); the model string routes to
    the matching provider via its prefix, picking up the API key from the
    environment automatically. The signature and chunk shape are the same the
    loop has consumed since Phase 3.

    model (Phase 13.6), when provided, overrides the module-level MODEL for this
    one turn — this is how the `--model` CLI flag selects a provider per run.
    When None (the default) MODEL is used, so existing callers are unaffected.

    When USE_CLAUDE_CLI is set (USE_CLAUDE_CLI_LLM=1), the LiteLLM call is
    skipped entirely and the turn is served by `claude -p` via _claude_cli_stream
    — a text-only fork that still yields the same OpenAI-format chunk shape.
    """
    # Lift image tool-results into real multimodal user messages so the model can
    # see them (a tool result is text-only on the wire), then route the turn: a
    # turn carrying an image goes to VLM_MODEL when configured, otherwise to the
    # caller's model (or the default MODEL). Text turns are unchanged.
    lifted = _lift_tool_image_results(messages)
    if VLM_MODEL and _contains_image(lifted):
        effective_model = VLM_MODEL
    else:
        effective_model = model or MODEL

    if USE_CLAUDE_CLI:
        async for chunk in _claude_cli_stream(lifted, system_prompt, effective_model):
            yield chunk
        return

    full_messages = [{"role": "system", "content": system_prompt}] + lifted
    # _thinking_kwargs carries max_tokens (and, when extended thinking is on and
    # the model supports it, the `thinking` param with a bumped max_tokens).
    base_kwargs = dict(
        model=effective_model,
        messages=full_messages,
        stream=True,
        # Ask for token usage on the final streamed chunk so /usage can report it.
        stream_options={"include_usage": True},
        **_thinking_kwargs(effective_model),
    )
    try:
        response = await litellm.acompletion(**base_kwargs, tools=TOOLS_SCHEMA, tool_choice="auto")
    except Exception as err:
        # Some backends reject any request carrying a `tools` array — notably
        # several Ollama models (gemma3, tinyllama) whose templates lack tool
        # support. Retry once without tools so the model can still answer (e.g.
        # the reasoning suite); any other failure propagates unchanged.
        if "does not support tools" not in str(err).lower():
            raise
        response = await litellm.acompletion(**base_kwargs)
    async for chunk in response:
        yield chunk


def _save_images_to_temp(
    content: object, temp_dir: Path | None = None
) -> tuple[list[dict], list[Path]]:
    """Extract images from content and save them to temp files.

    For multimodal content with image_url blocks, this extracts the base64 data,
    saves it to temp files, and replaces image blocks with text references to
    those file paths. This allows `claude -p` to read the images via its file
    reading capability instead of trying to pass base64 in the prompt.

    Returns:
        (modified_content, temp_files): Content with image blocks replaced by
        text references, and a list of temporary file paths to clean up later.
    """
    import base64
    import tempfile

    if isinstance(content, str):
        return [{"type": "text", "text": content}], []
    if not isinstance(content, list):
        return [{"type": "text", "text": str(content)}], []

    result: list[dict] = []
    temp_files: list[Path] = []

    for block in content:
        if not isinstance(block, dict):
            result.append({"type": "text", "text": str(block)})
            continue

        if block.get("type") == "text":
            result.append(block)
        elif block.get("type") == "image_url":
            # Extract base64 data from data URL
            image_url = block.get("image_url")
            raw_url = image_url.get("url", "") if isinstance(image_url, dict) else ""
            url = raw_url if isinstance(raw_url, str) else ""
            if url.startswith("data:"):
                # Parse data URL: data:image/png;base64,<data>
                try:
                    parts = url.split(",", 1)
                    if len(parts) == 2:
                        header, data = parts
                        # Determine file extension from mime type
                        ext = ".png"  # default
                        if "image/jpeg" in header or "image/jpg" in header:
                            ext = ".jpg"
                        elif "image/gif" in header:
                            ext = ".gif"
                        elif "image/webp" in header:
                            ext = ".webp"

                        # Decode and save to temp file
                        img_data = base64.b64decode(data)

                        if temp_dir:
                            # Use provided directory
                            temp_file = temp_dir / f"image_{len(temp_files)}{ext}"
                            temp_file.write_bytes(img_data)
                        else:
                            # Create temp file
                            fd, temp_path = tempfile.mkstemp(suffix=ext, prefix="claude_img_")
                            import os

                            os.write(fd, img_data)
                            os.close(fd)
                            temp_file = Path(temp_path)

                        temp_files.append(temp_file)

                        # Replace with text reference
                        result.append({"type": "text", "text": f"[Image file: {temp_file}]"})
                except Exception:
                    # If parsing fails, fall back to text placeholder
                    result.append({"type": "text", "text": "[image - failed to extract]"})
            else:
                # Non-data URL, keep as text placeholder
                result.append({"type": "text", "text": f"[image: {url}]"})
        else:
            result.append(block)

    return result, temp_files


def _flatten_content(content: object) -> str:
    """Render a message's content as plain text for the text-only CLI fork.

    Content is usually a string, but a multimodal user message (image paste) is a
    list of typed blocks — {"type": "text", ...} and {"type": "image_url", ...}.
    `claude -p` cannot receive image bytes through a flattened prompt, so text
    blocks are kept and image blocks become a clear placeholder (never the raw
    base64 payload). A plain string passes through unchanged.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return "" if content is None else str(content)
    rendered: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            rendered.append(str(block))
        elif block.get("type") == "text":
            rendered.append(str(block.get("text", "")))
        elif block.get("type") == "image_url":
            rendered.append("[image omitted — CLI fork is text-only]")
        else:
            rendered.append(str(block))
    return " ".join(part for part in rendered if part)


def _messages_to_prompt(system_prompt: str, messages: list[dict]) -> str:
    """Flatten the system prompt + message history into one text prompt.

    `claude -p` takes a single prompt string, not a structured message list, so
    we render the conversation as labelled turns. Tool messages are folded in as
    plain text — this fork is text-only, so there is no tool_calls structure to
    preserve, just the content the model needs to read. Multimodal content (image
    paste) is flattened via _flatten_content so the fork never chokes on a list.
    """
    parts = [f"System: {system_prompt}"]
    for msg in messages:
        role = msg.get("role", "user")
        content = _flatten_content(msg.get("content"))
        parts.append(f"{role.capitalize()}: {content}")
    return "\n\n".join(parts)


def _tool_result_chars(content: object) -> int:
    """Character count of a tool_result's content (a string or list of blocks)."""
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, dict):
                total += len(str(block.get("text", "")))
            else:
                total += len(str(block))
        return total
    return 0


def _parse_stream_json_line(line: bytes) -> list[dict]:
    """Normalize one `claude -p` stream-json NDJSON line into UI descriptors.

    The CLI interleaves several event shapes; we surface the ones the UI cares
    about and ignore all other noise (and any non-JSON line):

      text token   → {"kind": "text", "text": str}             (content_block_delta)
      tool began   → {"kind": "tool_start", "id", "name", "input"}  (assistant msg)
      tool result  → {"kind": "tool_end", "id", "is_error", "chars"}
                                                                (user tool_result)
      token usage  → {"kind": "usage", "prompt_tokens", "completion_tokens"}

    Tool calls are read from the *complete* assistant message (not the partial
    content_block_start) so the full input — which file, which command, the diff
    — is available; text still streams token-by-token from content_block_delta.

    The subprocess runs these tools itself, so tool descriptors are for display
    only — the caller emits them as events but never feeds them back into the
    agent's own tool loop. A message can carry several tool blocks, so this
    returns a list. Returns [] for noise or invalid JSON.
    """
    try:
        obj = json.loads(line)
    except (ValueError, TypeError):
        return []
    if not isinstance(obj, dict):
        return []

    # The complete assistant message carries finished tool_use blocks with full
    # input — the source for "which file / command / diff".
    if obj.get("type") == "assistant":
        content = (obj.get("message") or {}).get("content")
        if not isinstance(content, list):
            return []
        return [
            {
                "kind": "tool_start",
                "id": block.get("id") or "",
                "name": block.get("name") or "tool",
                "input": block.get("input") or {},
            }
            for block in content
            if isinstance(block, dict) and block.get("type") == "tool_use"
        ]

    # The terminal `result` event carries the run's token usage (input/output
    # tokens). Surface it so the closing chunk can carry it to /usage.
    if obj.get("type") == "result":
        usage = obj.get("usage")
        if isinstance(usage, dict):
            return [
                {
                    "kind": "usage",
                    "prompt_tokens": int(usage.get("input_tokens", 0)),
                    "completion_tokens": int(usage.get("output_tokens", 0)),
                }
            ]
        return []

    # Tool results arrive as a top-level `user` message, not a stream_event.
    if obj.get("type") == "user":
        content = (obj.get("message") or {}).get("content")
        if not isinstance(content, list):
            return []
        return [
            {
                "kind": "tool_end",
                "id": block.get("tool_use_id") or "",
                "is_error": bool(block.get("is_error")),
                "chars": _tool_result_chars(block.get("content")),
            }
            for block in content
            if isinstance(block, dict) and block.get("type") == "tool_result"
        ]

    if obj.get("type") != "stream_event":
        return []
    event = obj.get("event") or {}
    if event.get("type") == "content_block_delta":
        delta = event.get("delta") or {}
        if delta.get("type") == "text_delta" and delta.get("text"):
            return [{"kind": "text", "text": delta["text"]}]

    return []


async def _claude_cli_stream(
    messages: list[dict], system_prompt: str, model: str | None = None
) -> AsyncIterator[Any]:
    """Serve one turn by shelling out to `claude -p`, yielding OpenAI chunks.

    The subprocess runs the local Claude CLI in print mode with stream-json
    output (--output-format stream-json --verbose --include-partial-messages),
    so it emits one NDJSON event per token. We parse each line and yield a
    text_delta chunk for every `content_block_delta`, shaped exactly like the
    LiteLLM path's chunks — giving real token-by-token streaming the agent loop
    consumes without knowing the backend changed. A final empty chunk carries
    finish_reason="stop" to close the turn.

    The `claude -p` session runs its OWN tools internally, so TOOLS_SCHEMA is not
    forwarded and the agent's own tool loop is not driven here. Those tool calls
    would otherwise be invisible, so we parse the subprocess's tool_use /
    tool_result events and emit display-only tool_call_start / tool_call_end
    events (via renderer.emit) — the activity panel shows them, but they are
    never fed back into the agent loop (which would wrongly re-dispatch them).
    Each tool_use id is assigned a monotonic index so the panel keys distinct
    rows even across the multiple assistant messages in one subprocess run.

    Images (Phase N): Multimodal messages with inline base64 image data are
    preprocessed — images are saved to temp files and referenced by path in the
    prompt so `claude -p` can read them via its file reading capability. Temp
    files are cleaned up when streaming completes.
    """
    # Extract images from messages and save to temp files
    temp_files: list[Path] = []
    processed_messages = []
    for msg in messages:
        content = msg.get("content", "")
        modified_content, msg_temp_files = _save_images_to_temp(content)
        temp_files.extend(msg_temp_files)
        processed_messages.append({**msg, "content": modified_content})

    try:
        prompt = _messages_to_prompt(system_prompt, processed_messages)
        cmd = [
            "claude",
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--permission-mode",
            CLI_PERMISSION_MODE,
        ]
        if model:
            cmd += ["--model", model]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # Raise the StreamReader buffer well past asyncio's 64KB default: a
            # single stream-json line can be much larger (claude -p echoes the
            # image it read back as a base64 block, and our image cap is 5MB →
            # ~7MB once base64-expanded). The default makes readline() raise
            # LimitOverrunError mid-turn; _CLI_STREAM_LIMIT gives ample headroom.
            limit=_CLI_STREAM_LIMIT,
        )

        # stdout is typed Optional, but PIPE above guarantees a reader here.
        assert proc.stdout is not None
        # Map each tool_use id to a monotonic display index so the activity panel
        # keys distinct rows (block indices reset per assistant message and would
        # otherwise collide across a multi-step subprocess run).
        id_to_index: dict[str, int] = {}
        next_index = 0
        final_usage: dict | None = None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            for descriptor in _parse_stream_json_line(line):
                kind = descriptor["kind"]
                if kind == "usage":
                    final_usage = {
                        "prompt_tokens": descriptor["prompt_tokens"],
                        "completion_tokens": descriptor["completion_tokens"],
                    }
                elif kind == "text":
                    yield _chunk(content=descriptor["text"])
                elif kind == "tool_start":
                    id_to_index[descriptor["id"]] = next_index
                    renderer.emit(
                        {
                            "type": "tool_call_start",
                            "index": next_index,
                            "tool_call_id": descriptor["id"],
                            "name": descriptor["name"],
                            "input": descriptor.get("input") or {},
                        }
                    )
                    next_index += 1
                elif kind == "tool_end":
                    index = id_to_index.get(descriptor["id"])
                    if index is None:
                        continue  # a result with no matching start — nothing to resolve
                    renderer.emit(
                        {
                            "type": "tool_call_end",
                            "index": index,
                            "tool_call_id": descriptor["id"],
                            "is_error": descriptor["is_error"],
                            "chars": descriptor["chars"],
                        }
                    )

        await proc.wait()
        # Close the turn so the loop's finish_reason check fires (no tool calls),
        # carrying the run's token usage when the result event reported it.
        yield _chunk(finish_reason="stop", usage=final_usage)
    finally:
        # Clean up temp image files
        for temp_file in temp_files:
            try:
                temp_file.unlink()
            except Exception:
                pass  # Best effort cleanup
