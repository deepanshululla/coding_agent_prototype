# Tutorial implementation plans

One implementation plan per tutorial stage and sub-stage (mirrors `website/docs/tutorial/`).
Each plan follows the repo [`_template.md`](../_template.md) format — Status, Goal, Files
changed, Order of operations, Verification (with the stage's BDD gate) — so the agent
documented in the tutorial can actually be built, one verifiable slice at a time.

These live in a subfolder (not the dated flat `plans/` convention) because they form one
cohesive, phase-ordered set. Build order = file order.

## Core build

- [Phase 1 — Talk to a Model](./phase-01-talk-to-a-model.md)
- [Phase 2 — The Conversation Loop](./phase-02-the-agent-loop.md)
- [Phase 3 — Streaming Responses](./phase-03-streaming.md)
- [Phase 4 — Your First Tool](./phase-04-your-first-tool.md)
- [Phase 5 — Streaming Tool Calls](./phase-05-streaming-tool-calls.md)
- [Phase 6 — A Toolbox](./phase-06-a-toolbox.md)
- [Phase 7 — Parallel Tool Execution](./phase-07-parallel-tools.md)
- [Phase 8 — System Prompt & CLI](./phase-08-system-prompt-and-cli.md)
- [Phase 9 — Testing the Agent](./phase-09-testing-the-agent.md)

## Phase 10 — Terminal UI (layers)

- [10.1 — The emit() Seam](./phase-10-1-event-seam.md)
- [10.2 — The Transcript Pane](./phase-10-2-transcript.md)
- [10.3 — The Tool Panel](./phase-10-3-tool-panel.md)
- [10.4 — Input & Status Bar](./phase-10-4-input-status.md)
- [10.5 — Keybindings & Themes](./phase-10-5-keys-themes.md)

## Phase 11 — Add LiteLLM

- [Phase 11 — Add LiteLLM](./phase-11-add-litellm.md)

## Phase 12 — Harden It (layers)

- [12.1 — Security Model](./phase-12-1-security-model.md)
- [12.2 — Command Allowlist](./phase-12-2-command-allowlist.md)
- [12.3 — Permissions & Modes](./phase-12-3-permissions-and-modes.md)
- [12.4 — Sandboxing](./phase-12-4-sandboxing.md)
- [12.5 — Logging & Settings](./phase-12-5-logging-and-settings.md)

## Phase 13 — Extend It (layers)

- [13.1 — Project Instructions](./phase-13-1-project-instructions.md)
- [13.2 — Prompt Templates & Hooks](./phase-13-2-prompt-templates-and-hooks.md)
- [13.3 — Skills](./phase-13-3-skills.md)
- [13.4 — Agent Skills](./phase-13-4-agent-skills.md)
- [13.5 — MCP Integration](./phase-13-5-mcp-integration.md)
- [13.6 — Custom Models & Providers](./phase-13-6-models-and-providers.md)

## Phase 14 — Interface It (layers)

- [14.1 — The SDK](./phase-14-1-sdk.md)
- [14.2 — RPC Mode](./phase-14-2-rpc-mode.md)
- [14.3 — JSON Event Stream](./phase-14-3-json-event-stream.md)

## Frontier

- [Phase 15 — Steering](./phase-15-steering.md)
- [Phase 16 — Context Compaction](./phase-16-context-compaction.md)
- [Phase 17 — Extended Thinking](./phase-17-extended-thinking.md)
