---
sidebar_position: 13.5
title: Architecture Decisions
description: A log of significant architecture decisions (ADRs) for the agent — the context, the decision, and its consequences.
---

# Architecture Decisions

This is the project's **decision log** — short records of significant architectural choices, in
the [ADR](https://adr.github.io/) style. Each entry captures the *context* (what forced a
decision), the *decision* itself, and the *consequences* (what it buys and costs). The point is
that a future reader — human or agent — can see *why* the code is shaped the way it is, not just
*what* it does.

Entries are in conceptual order: the foundational decisions first, the most recent at the end.
Each ADR has a **status**:

- **Accepted** — decided and reflected in the docs/code.
- **Deferred** — deliberately *not* done yet, with a recommendation for when to revisit.
- **Superseded** — replaced by a later ADR (linked).

| # | Decision | Status |
|---|---|---|
| [ADR-0001](#adr-0001--the-agent-is-a-hand-rolled-loop-no-framework) | The agent is a hand-rolled loop (no framework) | Accepted |
| [ADR-0002](#adr-0002--one-litellm-call-instead-of-per-provider-adapters) | One LiteLLM call instead of per-provider adapters | Accepted |
| [ADR-0003](#adr-0003--openai-style-tool-schemas-as-the-canonical-format) | OpenAI-style tool schemas as the canonical format | Accepted |
| [ADR-0004](#adr-0004--tools-return-error-strings-never-raise) | Tools return error strings, never raise | Accepted |
| [ADR-0005](#adr-0005--execute-tool-calls-in-parallel-on-an-async-core) | Execute tool calls in parallel on an async core | Accepted |
| [ADR-0006](#adr-0006--buffer-streaming-tool-call-arguments-parse-once) | Buffer streaming tool-call arguments, parse once | Accepted |
| [ADR-0007](#adr-0007--minimal-message-types-plain-dicts-on-the-wire) | Minimal message types; plain dicts on the wire | Accepted |
| [ADR-0008](#adr-0008--bound-the-loop-with-max_iterations) | Bound the loop with MAX_ITERATIONS | Accepted |
| [ADR-0009](#adr-0009--stdout-only-core-tui-is-an-opt-in-renderer) | stdout-only core; TUI is an opt-in renderer | Accepted |
| [ADR-0010](#adr-0010--configuration-via-agent_-env-vars-fail-closed) | Configuration via `AGENT_*` env vars, fail-closed | Accepted |
| [ADR-0011](#adr-0011--adopt-the-open-agent-skills-standard) | Adopt the open Agent Skills standard | Accepted |
| [ADR-0012](#adr-0012--merge-mcp-tools-into-the-same-registry) | Merge MCP tools into the same registry | Accepted |
| [ADR-0013](#adr-0013--command-allowlist-is-default-deny) | Command allowlist is default-deny | Accepted |
| [ADR-0014](#adr-0014--defer-the-http-serving-layer-fastapi--granian) | Defer the HTTP serving layer (FastAPI + Granian) | Deferred |
| [ADR-0015](#adr-0015--one-model-per-loop-defer-dual-model-role-routing) | One model per loop; defer dual-model role routing | Deferred |

---

## ADR-0001 — The agent is a hand-rolled loop (no framework)

**Status:** Accepted.

### Context

LangChain and LangGraph package the agent loop as a framework abstraction. The goal of this
project is to *understand* that loop by owning it, not to depend on someone else's version.

### Decision

Implement the loop directly: a nested outer/inner `while` in `src/agent.py`. The inner loop
streams a response, executes tool calls, appends results, and repeats until the model returns
text with no tool calls; the outer loop exists only for follow-up/steering messages. See
[The Agent Loop](./architecture/the-agent-loop.md).

### Consequences

The whole agent is ~750 lines with no framework lock-in and nothing hidden. Cost: features a
framework would give for free (memory, hooks, persistence) are ours to build — tracked as their
own decisions and [planned features](./differences-from-pi.md).

---

## ADR-0002 — One LiteLLM call instead of per-provider adapters

**Status:** Accepted.

### Context

pi.dev maintains 40+ provider adapters with per-provider streaming parsers (`packages/ai/`). This
project's goal is to teach the loop, not provider plumbing.

### Decision

Use a single `litellm.acompletion(..., stream=True)` call. The model string selects the provider;
LiteLLM normalizes every provider to the OpenAI chunk format. See
[The Provider Layer](./architecture/provider-layer.md). (An optional
[Claude CLI backend](./customization/claude-cli-backend.md) exists as a second route.)

### Consequences

Swapping providers is a one-string change with zero provider-specific code. Cost: a dependency on
LiteLLM's normalization, and you inherit its abstraction rather than a provider's raw event format.

---

## ADR-0003 — OpenAI-style tool schemas as the canonical format

**Status:** Accepted.

### Context

Tools must be described to the model in *some* schema. Anthropic uses `input_schema`; OpenAI uses a
`{"type": "function", "function": {…, "parameters": …}}` envelope. We talk to providers through
LiteLLM (see [ADR-0002](#adr-0002--one-litellm-call-instead-of-per-provider-adapters)).

### Decision

Define every tool with the **OpenAI-style** schema in `TOOLS_SCHEMA`. LiteLLM translates it to
whatever the underlying provider needs. See [Tool Schema Format](./tools/schema-format.md).

### Consequences

One schema works across all providers; no per-provider tool definitions. The same envelope is what
[MCP tools](./mcp/mcp-as-tools.md) are adapted into, so built-in and external tools share a format.
Cost: it looks "OpenAI-shaped" even when running on Claude — a minor readability surprise.

---

## ADR-0004 — Tools return error strings, never raise

**Status:** Accepted.

### Context

A tool can fail (missing file, non-zero `bash` exit, ambiguous edit). The loop must keep going and
let the *model* decide how to recover.

### Decision

Tools **return a descriptive string** and set `ToolResult.is_error=True` on failure; they never
raise. The loop appends the error as a normal tool result and the model reads it and adapts. See
[Error Handling](./tools/error-handling.md).

### Consequences

The model recovers on its own (retries, alternatives) instead of the loop crashing. Cost: every
tool must catch its own exceptions; a stray raise is a bug, guarded by a fallback `try/except` in
`_execute_one_tool`.

---

## ADR-0005 — Execute tool calls in parallel on an async core

**Status:** Accepted.

### Context

A single model turn can request several tool calls at once, and `litellm.acompletion` is
non-blocking. Running tools one at a time would waste that.

### Decision

Make the whole agent `async`. Execute all of a turn's tool calls concurrently with
`asyncio.gather`, and wrap blocking I/O (subprocess, file reads) in `asyncio.to_thread` so it
doesn't stall the event loop. See [Parallel Execution](./tools/parallel-execution.md) and
[Async & Concurrency](./concepts/async-and-concurrency.md).

### Consequences

Turns with multiple tools finish in the time of the slowest one, and the loop stays responsive.
Cost: async complexity, and every tool author must avoid blocking the loop (hence `to_thread`).

---

## ADR-0006 — Buffer streaming tool-call arguments, parse once

**Status:** Accepted.

### Context

In the streamed response, a tool call's `arguments` arrive as **partial JSON strings** spread
across many chunks, and `id`/`name` appear only on the first chunk for each call index.

### Decision

Accumulate fragments **by index** during the stream and `json.loads` the arguments **once**, after
the stream ends (when `finish_reason` is set). Never parse mid-stream. See
[Streaming & Event Accumulation](./architecture/streaming-and-events.md).

### Consequences

Robust parsing regardless of how the provider chunks output. Cost: a tool call can't be dispatched
until its turn's stream completes — acceptable, since arguments aren't valid JSON until then.

---

## ADR-0007 — Minimal message types; plain dicts on the wire

**Status:** Accepted.

### Context

pi.dev uses a rich content-block hierarchy (`TextContent`, `ThinkingContent`, `ImageContent`, …).
That's powerful but heavy for a learning project.

### Decision

Keep three small dataclasses (`ToolCall`, `ToolResult`, `Message`) for internal handles, and pass
**plain dicts** on the wire — the providers accept them directly. The module is named `types_`
(trailing underscore) to avoid shadowing the stdlib `types`. See
[Message Types](./architecture/message-types.md).

### Consequences

Simple, readable message flow. Cost: less type safety and no first-class support for thinking or
image blocks — revisit if those become requirements (see [Extended Thinking](./advanced/extended-thinking.md)).

---

## ADR-0008 — Bound the loop with MAX_ITERATIONS

**Status:** Accepted.

### Context

An agent loop can run indefinitely — the model can keep calling tools without ever finishing.

### Decision

Cap the inner loop at `MAX_ITERATIONS = 30` cycles. When the cap is hit, the loop exits regardless
of whether the task is "done." See [Settings Reference](./operations/settings.md).

### Consequences

A hard stop against runaway cost and infinite loops. Cost: the loop exits **silently** at the cap,
so an unfinished complex task can look like a quiet failure — check the iteration count when an
agent stops early.

---

## ADR-0009 — stdout-only core; TUI is an opt-in renderer

**Status:** Accepted.

### Context

pi.dev ships a full terminal UI (`packages/tui/`). A TUI is thousands of lines that teach nothing
about the agent loop, which is the point of this project.

### Decision

The core prints to **stdout**. The [Terminal UI](./terminal-ui/overview.md) is an **opt-in
renderer** (`AGENT_UI=tui`) layered over an `emit()` event seam, so the loop is unchanged whether
output goes to stdout or a full-screen app.

### Consequences

The core stays minimal and the loop easy to follow; the TUI and the
[JSON event stream](./programmatic-usage/json-event-stream.md) become two renderers of the same
events. Cost: the `emit()` seam must exist before either non-stdout renderer can be built.

---

## ADR-0010 — Configuration via `AGENT_*` env vars, fail-closed

**Status:** Accepted.

### Context

Tunables (model, token/iteration limits, tool caps) started as literal module constants, requiring
a code edit to change. Options were a config file, CLI flags, or environment variables.

### Decision

Layer `AGENT_*` environment variables over a small `src/config.py` reader whose **defaults equal
the shipped constants**. Security-sensitive values fail **closed** — `AGENT_BASH_ALLOWLIST` defaults
to empty (deny), a bad integer raises rather than silently defaulting. See
[Settings Reference](./operations/settings.md).

### Consequences

Configurable via `.env` without touching code; behavior is identical when nothing is set. Cost: a
thin config module and discipline about load order (`load_dotenv()` before `config` is imported).

---

## ADR-0011 — Adopt the open Agent Skills standard

**Status:** Accepted.

### Context

Skills (named instruction blocks) could be a bespoke format. But an open standard
([Agent Skills](https://agentskills.io), `SKILL.md` folders) is already adopted across many agents.

### Decision

Be **spec-compliant**: load `SKILL.md` skills with the standard frontmatter and validation, and use
**progressive disclosure** — advertise `name`+`description`, load a skill's body on demand via a
`load_skill` tool. Read both bundled and already-installed skills. See
[Installing Agent Skills](./customization/installing-claude-skills.md) and
[Reading Installed Skills](./customization/reading-installed-skills.md).

### Consequences

Skills are portable to/from any compliant client (Claude Code, Cursor, etc.) and cost ~one line of
context until used. Cost: a loader + validation, and skills are an untrusted prompt-injection
surface to vet (see [ADR-0013](#adr-0013--command-allowlist-is-default-deny)).

---

## ADR-0012 — Merge MCP tools into the same registry

**Status:** Accepted.

### Context

External tools can be added via the Model Context Protocol. They could run through a separate code
path, or be made to look like native tools.

### Decision

Adapt each MCP tool's schema into the OpenAI envelope, append it to `TOOLS_SCHEMA`, and register a
forwarding wrapper in `TOOL_REGISTRY` — so MCP tools are **indistinguishable from built-ins** in the
loop. See [MCP Tools in the Loop](./mcp/mcp-as-tools.md).

### Consequences

One dispatch path; the loop doesn't know or care whether a tool is built-in or remote. Cost: an
adapter and per-server connection lifecycle, plus the same trust concerns as any external code
([ADR-0013](#adr-0013--command-allowlist-is-default-deny)).

---

## ADR-0013 — Command allowlist is default-deny

**Status:** Accepted.

### Context

The `bash` tool runs whatever the model asks via `subprocess.run(..., shell=True)` — the single
largest risk surface in the agent.

### Decision

The optional command allowlist is **default-deny**: match on the program name (`argv[0]`), and
**reject shell metacharacters** (`;`, `|`, `$()`, backticks, redirects) that defeat parsing, rather
than try to allow compound commands. A refusal is returned to the model as a tool error so it can
adapt. See [Command Allowlist](./operations/command-allowlist.md).

### Consequences

A trustworthy gate that can't be bypassed by command chaining or substitution. Cost: legitimate
compound commands (`cd build && make`) are blocked — the model must issue one simple command per
call, or you opt into running without `shell=True`.

---

## ADR-0014 — Defer the HTTP serving layer (FastAPI + Granian)

**Status:** Deferred (2026-06-20) · recommend adding when a network boundary is genuinely needed.

### Context

`run_agent` is an `async` coroutine. The ways to drive it are all process-level today: in-process
(`await run_agent(...)`, see [SDK](./programmatic-usage/sdk.md)) or a stdlib stdin/stdout JSON-RPC
loop ([RPC Mode](./programmatic-usage/rpc-mode.md)). The question was whether to stand up an HTTP
service — **FastAPI** (framework) on **Granian** (ASGI server) — now. This is a terminal agent, not
a web service, and it runs arbitrary `bash`, so an HTTP layer adds dependencies and a network
surface in front of shell execution.

### Decision

**Do not build the HTTP layer yet.** Keep the default interfaces process-level. Document the
FastAPI + Granian design in [RPC Mode](./programmatic-usage/rpc-mode.md), ready to implement.

**Recommendation:** add the **FastAPI + Granian** layer when at least one of these is real:

- a **browser or remote UI** needs to drive the agent;
- a **non-Python or remote caller** must reach it (can't just spawn a subprocess);
- **multiple concurrent clients** need one long-lived service rather than process-per-task.

Then: FastAPI for routing/validation/`StreamingResponse`, Granian as the ASGI server (replacing
uvicorn, not FastAPI), bound to `127.0.0.1` by default. Low-regret, because stdio doesn't preclude
HTTP — a thin FastAPI adapter wraps the same coroutine.

### Consequences

**Positive:** zero new dependencies; no network attack surface in front of `bash`
([Security Model](./operations/security.md)); simple lifecycle; streaming is just NDJSON on stdout.
**Deferred cost:** no network reachability until built; we forgo FastAPI's free validation/OpenAPI;
cross-process callers manage a subprocess instead of hitting a URL.

### Alternatives considered

- **FastAPI + Granian now** — rejected as premature; the benefits are latent for a single-user
  terminal agent.
- **FastAPI on uvicorn** — same framework benefits; Granian preferred for the eventual server (Rust
  core, HTTP/2, single binary).
- **Raw ASGI / RSGI, no framework** — rejected; hand-rolls routing/validation for no gain over
  stdio (simpler) or FastAPI (richer).

---

## ADR-0015 — One model per loop; defer dual-model role routing

**Status:** Deferred (2026-06-21) · recommend the **delegation-tool** design when a true
reasoning/coding split is genuinely wanted; ship a single-model Ollama task now.

### Context

Running locally against [Ollama](https://ollama.com) raises a tempting idea: pair a strong
*reasoning / tool-calling* model (e.g. `gpt-oss:120b`) with a specialized *coding* model (e.g.
`qwen3-coder:30b`), each doing what it is best at. But the loop is built around **one** `model`
threaded end to end — `config.MODEL` → `run_agent(model=…)` → `stream_turn` →
`provider.stream_response` (see [ADR-0002](#adr-0002--one-litellm-call-instead-of-per-provider-adapters)
and the [Provider Layer](./architecture/provider-layer.md)). A single turn reasons, calls tools,
*and* edits code with that one model, so "use model X for coding, model Y for everything else" is
not a config toggle — it needs a routing seam. The question is which seam, and whether the split
earns its complexity.

### Decision

**Keep one model per loop as the default**, and add a single-model `task tui:ollama` entry pointed
at one Ollama model (a one-string change, [ADR-0010](#adr-0010--configuration-via-agent_-env-vars-fail-closed)).
**Defer** dual-model role routing until it is genuinely wanted, and when it is, prefer the
**delegation-tool** design: the reasoning model drives the loop and a new `write_code` tool hands a
focused instruction to a `qwen3-coder` sub-agent that performs the edits. It is the only option
where "coding" is a *crisp* boundary (the tool call) rather than a heuristic, and it reuses the
existing tool registry and the sub-agent spawn pattern already in
`src/architectures/orchestrator_worker.py`.

### Consequences

**Positive:** the loop stays single-model and easy to follow; local Ollama users get a working
`tui:ollama` immediately with zero new abstractions; the eventual dual-model path is low-regret
because the delegation tool slots into the existing registry without touching the core loop.
**Deferred cost:** until built, one local model does both reasoning and coding, so you can't pair a
big reasoner with a small specialist; the delegation design, when added, costs a tool, sub-agent
wiring, and prompt guidance so the driver delegates instead of editing directly.

### Alternatives considered

- **Delegation tool** (recommended when pursued) — driver = `gpt-oss:120b`; a `write_code` tool runs
  a `qwen3-coder:30b` sub-agent with read/edit/write tools. *Pros:* truest to intent, each model
  plays to its strength, the coder gets fresh focused context, the split is crisp. *Cons:* most new
  code; two-hop latency; the driver sees only the coder's result; depends on the driver choosing to
  delegate.
- **Per-turn router** — pick the model each turn (coder when the turn will edit, reasoner otherwise).
  *Pros:* no new tool, one loop preserved. *Cons:* you can't know a turn will edit code before the
  model responds, so routing is a fragile heuristic; real turns mix reasoning *and* edits, making the
  split artificial; swapping models mid-context mixes two styles. Rejected as imprecise.
- **Orchestrator-worker, per-role models** — orchestrator (decompose/synthesize) on `gpt-oss`,
  workers on `qwen3-coder`, reusing the existing architecture
  ([Plugin Architecture](./architecture-patterns/plugin-architecture.md)). *Pros:* least new code.
  *Cons:* workers still reason and call tools, so it isn't a pure coding model and doesn't match the
  mental model; decompose/synthesize overhead on every task. The cheap fallback if a new tool is
  unwanted.
- **Single model only** — `tui:ollama` on one model. *Pros:* trivial, ships now. *Cons:* no split at
  all. Chosen as the immediate step, not the end state.

---

## Adding a new decision

Copy the template, increment the number, and add a row to the index table:

```markdown
## ADR-00NN — <short title>

**Status:** Accepted | Deferred | Superseded by [ADR-XXXX](#...)

### Context
<what forced a decision>

### Decision
<what we chose>

### Consequences
<what it buys, what it costs>

### Alternatives considered
<options weighed and why they lost>
```
