---
sidebar_position: 19
title: "Phase 18 — Go Further & Close"
description: Specify agent behavior with BDD integration testing, explore architecture patterns for the next step, and close the tutorial.
---

# Phase 18 — Go Further & Close

:::note Starting point
The agent with steering, context compaction, and extended thinking from Phases 15–17. Every capability introduced in this tutorial is in place. This is the final phase.
:::

Three things remain: a way to specify and verify what the agent *does* (not just that the loop mechanics work), pointers to structural patterns for evolving the agent beyond v1, and a close of the tutorial itself.

## Specify behavior with BDD integration testing

The `ScriptedLLM` pattern from Phase 9 is a foundation for a full BDD testing framework. The framework adds a `conftest.py` with an `AgentWorld` fixture, `pytest-bdd` feature files in Gherkin, and a taxonomy of behavioral assertions covering tool call sequence, filesystem effects, error recovery, parallel dispatch, and the `MAX_ITERATIONS` guard.

If you want to specify and verify what the agent *does* — not just that the loop accumulates chunks correctly — this is the right layer:

```gherkin
Scenario: Agent reads a file before editing it
  Given a file "hello.py" containing a greeting function
  And the scripted model will call read_file then edit_file
  When the agent is asked to "change the greeting to goodbye"
  Then the tool call log contains "read_file" before "edit_file"
  And the file "hello.py" contains "goodbye"
```

Full setup, step definitions, and a taxonomy of eight assertion classes: [BDD Integration Testing](../guides/bdd-integration-testing.md).

### Behavior (BDD)

Verify the whole agent as a **BDD gate** — run the meta-scenario below twice:

1. **Before verification (red):** run it *before* all prior phases' *Build it* code is in place — it must **fail**, naming the gate that isn't yet passing.
2. **After verification (green):** run it *after* all phases are implemented — it must **pass**, proving the full agent is verifiably correct end-to-end.

```gherkin
Scenario: Every phase's BDD gate passes — the whole agent is verifiably correct
  Given all phases 1–17 have been implemented
  And the BDD feature suite exists under tests/features/
  When the full BDD suite is run with "uv run pytest tests/features/ -v"
  Then every scenario passes
  And no scenario is skipped or marked xfail without a recorded reason
  And the tool call logs, filesystem effects, and final answers match their specifications
```

Run this with the [BDD framework](../guides/bdd-integration-testing.md). The suite should include at minimum: a safe-edits scenario (read before edit), an error-recovery scenario, a parallel-tools scenario, a MAX_ITERATIONS guard scenario, a steering scenario, and a compaction coherence scenario.

## Architecture patterns

Once the v1 agent is solid, the natural next step is structural: make the design explicit at the architecture level rather than implicit in a single `run_agent` function.

:::tip Architecture patterns
Going further *structurally*, not just feature-wise: make the loop an explicit [State Machine](../architecture-patterns/state-machine.md), split [Planner / Executor](../architecture-patterns/planner-executor.md), keep an [event-sourced run log](../architecture-patterns/event-sourcing.md), isolate edits in [Worktrees](../architecture-patterns/worktrees.md), and route tasks with [Chain of Responsibility](../architecture-patterns/chain-of-responsibility.md) + [Strategy](../architecture-patterns/strategy-pattern.md). The full catalog: [Architecture Patterns](../architecture-patterns/overview.md).
:::

These are not prerequisites for a working agent. They are patterns that become relevant when the agent grows: multiple task types, concurrent runs, audit requirements, or the need to swap strategies at runtime.

## Closing the tutorial

You started with a single `claude -p` call behind a small wrapper class — no SDK, no API key abstraction — and built, phase by phase, a complete coding agent, swapping in LiteLLM for multi-provider support at [Phase 11](./11-add-litellm.md). Every abstraction was introduced when it was needed, tested before the next layer arrived, and grounded in the real source files in this repo.

Two reference documents close the loop on the design decisions you may have wondered about along the way:

- [Architecture Decisions](../architecture-decisions.md) — A log of every significant design decision with the reasoning behind it: why LiteLLM instead of a hand-rolled provider layer, why `types_.py` and not `types.py`, why errors are returned as strings rather than raised, and more.

- [Differences from pi.dev](../differences-from-pi.md) — This project mirrors [pi.dev](https://pi.dev) but diverges in specific ways. This page catalogs each difference: stdout-only vs. TUI, LiteLLM vs. a custom provider layer, and features intentionally omitted from v1.

The agent you have built is the same one that lives in `src/`. `uv run pytest -q` passes. `uv run main.py "…"` works. Everything after Phase 9 is a choice you make based on what you want the agent to do next.
