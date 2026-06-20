---
sidebar_position: 7
title: State Machine
description: Replace the agent's free-form inner loop with an explicit state machine — INIT → GATHER_CONTEXT → PLAN → EDIT → TEST → FIX_ERRORS → REVIEW_DIFF → DONE — so each phase has clear entry/exit conditions, per-state tool budgets, and no uncontrolled wandering.
---

# State Machine

The inner loop in `run_agent` advances through logical phases: stream a response, execute tools, repeat. But the loop does not know *which* phase it is in. The model can call `write_file` in what should be a read-only exploration phase, or loop through twenty iterations of `bash` without ever checking its own diff. Making the loop an explicit state machine eliminates that wandering by encoding valid transitions and per-state constraints in data, not prose.

:::note Design guidance, not v1
The current `run_agent` is a flat `while` loop gated only by `MAX_ITERATIONS = 30`. The state machine described here replaces that gate with per-state budgets and explicit transitions. The shipped core is intentionally simpler — adopt this when you find the agent looping unproductively or drifting into the wrong phase.
:::

## The problem

The current inner loop (phases A–E in `src/agent.py`) is correct but implicit:

```
Phase A: stream from the model
Phase B: append assistant turn
Phase C: stop if no tool calls
Phase D: execute tools in parallel
Phase E: push tool results
```

Nothing in the code prevents the model from:

- Reading files for fifteen iterations before ever editing anything.
- Running tests before having made any edits.
- Re-editing a file it already fixed, causing a regress.
- Spending all 30 iterations in exploration and never reaching a commit.

`MAX_ITERATIONS = 30` is a hard ceiling, not a structure. When it fires, the agent stops wherever it happens to be.

## The pattern

Replace the flat iteration counter with an enum of named states, an explicit transition table, and per-state iteration budgets. The loop advances through states in order; each state controls which tools are available and how many iterations it may spend.

```
                     ┌──────────────────────────────────────────────┐
                     │                                              │
       task ──▶  INIT ──▶ GATHER_CONTEXT ──▶ PLAN ──▶ EDIT ──▶ TEST
                                                          ▲         │
                                                          │         ▼
                                                    FIX_ERRORS ◀────┘
                                                          │
                                                          ▼
                                                   REVIEW_DIFF ──▶ DONE
```

State transitions fire on observable signals: the model declares it has finished gathering context, tests pass, the diff is clean. Transitions that skip ahead (GATHER → EDIT without PLAN) are illegal; transitions that loop back (TEST → FIX_ERRORS → EDIT) are bounded.

## In this project

### Mapping phases A–E onto states

| Current phase in `run_agent` | State in the machine | Key constraint |
|---|---|---|
| `run_agent` entry | `INIT` | Set up history, choose strategy |
| First iterations — model reads files | `GATHER_CONTEXT` | Read-only tools only |
| Model produces a plan in text | `PLAN` | No tool calls expected; model responds with a plan |
| Model edits files | `EDIT` | Write tools allowed; read tools allowed; no `bash` test runs |
| Model runs tests | `TEST` | `bash` only; no file edits |
| Model fixes failing tests | `FIX_ERRORS` | All tools; bounded re-entry to EDIT |
| Model reviews its own diff | `REVIEW_DIFF` | Read + `bash` (git diff); no edits |
| Loop exits | `DONE` | No further iterations |

### The enum and transition table

```python
# src/state_machine.py (planned)
from __future__ import annotations
from enum import Enum, auto
from typing import NamedTuple


class AgentState(Enum):
    INIT          = auto()
    GATHER_CONTEXT = auto()
    PLAN          = auto()
    EDIT          = auto()
    TEST          = auto()
    FIX_ERRORS    = auto()
    REVIEW_DIFF   = auto()
    DONE          = auto()


class StateConfig(NamedTuple):
    max_iterations: int          # budget for this state
    allowed_tools: set[str] | None  # None = all tools
    next_state: AgentState | None   # None = determined at runtime


# Per-state budgets and tool allowlists
STATE_CONFIG: dict[AgentState, StateConfig] = {
    AgentState.INIT: StateConfig(
        max_iterations=1,
        allowed_tools=None,
        next_state=AgentState.GATHER_CONTEXT,
    ),
    AgentState.GATHER_CONTEXT: StateConfig(
        max_iterations=8,
        allowed_tools={"read_file", "grep", "find_files", "list_dir"},
        next_state=AgentState.PLAN,
    ),
    AgentState.PLAN: StateConfig(
        max_iterations=2,
        allowed_tools=set(),      # expect a text-only response
        next_state=AgentState.EDIT,
    ),
    AgentState.EDIT: StateConfig(
        max_iterations=10,
        allowed_tools={
            "read_file", "write_file", "edit_file",
            "grep", "find_files", "list_dir",
        },
        next_state=AgentState.TEST,
    ),
    AgentState.TEST: StateConfig(
        max_iterations=4,
        allowed_tools={"bash"},
        next_state=AgentState.REVIEW_DIFF,  # overridden if tests fail
    ),
    AgentState.FIX_ERRORS: StateConfig(
        max_iterations=6,
        allowed_tools=None,       # all tools; model needs full access to fix
        next_state=AgentState.TEST,
    ),
    AgentState.REVIEW_DIFF: StateConfig(
        max_iterations=2,
        allowed_tools={"read_file", "bash"},
        next_state=AgentState.DONE,
    ),
    AgentState.DONE: StateConfig(
        max_iterations=0,
        allowed_tools=set(),
        next_state=None,
    ),
}
```

### Transition logic

State transitions are driven by signals from the current iteration's outcome. Each state has a `should_advance(messages, tool_results)` check:

```python
# src/state_machine.py (planned, continued)
from tools import TOOL_REGISTRY


def filter_tools_for_state(state: AgentState) -> dict:
    allowed = STATE_CONFIG[state].allowed_tools
    if allowed is None:
        return TOOL_REGISTRY
    return {k: v for k, v in TOOL_REGISTRY.items() if k in allowed}


def next_state_after(
    current: AgentState,
    tool_results: list[dict],
    iteration_in_state: int,
) -> AgentState:
    """Compute the next state based on current state and what just happened."""
    config = STATE_CONFIG[current]

    if current == AgentState.TEST:
        # Did any bash tool result contain a test failure?
        test_failed = any(
            "FAILED" in (r.get("content") or "") or
            "error" in (r.get("content") or "").lower()
            for r in tool_results
        )
        if test_failed:
            return AgentState.FIX_ERRORS
        return AgentState.REVIEW_DIFF

    if current == AgentState.FIX_ERRORS:
        # After fixing, re-enter TEST regardless
        return AgentState.TEST

    if iteration_in_state >= config.max_iterations:
        # Budget exhausted: advance to the next state
        return config.next_state or AgentState.DONE

    return current  # stay in this state
```

### The stateful loop

```python
# src/agent.py — state-machine variant (planned)
from state_machine import AgentState, STATE_CONFIG, filter_tools_for_state, next_state_after

async def run_agent_stateful(task: str, system_prompt: str) -> list[dict]:
    messages: list[dict] = [{"role": "user", "content": task}]
    state = AgentState.GATHER_CONTEXT
    iteration_in_state = 0
    total_iterations = 0

    while state != AgentState.DONE:
        total_iterations += 1
        config = STATE_CONFIG[state]
        tool_registry = filter_tools_for_state(state)

        # ── Phase A: stream ──────────────────────────────────────────────
        # (identical to run_agent phases A–E, but uses tool_registry instead
        #  of the global TOOL_REGISTRY, and respects state's max_iterations)
        tool_results, text_buf = await _one_iteration(messages, system_prompt, tool_registry)
        iteration_in_state += 1

        # ── Transition check ─────────────────────────────────────────────
        new_state = next_state_after(state, tool_results, iteration_in_state)
        if new_state != state:
            print(f"\n[state] {state.name} → {new_state.name}")
            state = new_state
            iteration_in_state = 0

        # Safety ceiling across all states
        if total_iterations >= 30:
            print("[state] MAX_ITERATIONS reached — stopping")
            break

    return messages
```

### Per-state budgets replace `MAX_ITERATIONS`

`MAX_ITERATIONS = 30` becomes a safety ceiling that is rarely reached in practice because each state's `max_iterations` exhausts the local budget first:

| State | Budget | Cumulative ceiling |
|---|---|---|
| INIT | 1 | 1 |
| GATHER_CONTEXT | 8 | 9 |
| PLAN | 2 | 11 |
| EDIT | 10 | 21 |
| TEST | 4 | 25 |
| FIX_ERRORS | 6 | 31 |
| REVIEW_DIFF | 2 | 33 |

The sum already exceeds 30, so the global ceiling still matters as a hard backstop — but it no longer determines where the agent stops. The state machine does.

### States constrain which tools are allowed

The `filter_tools_for_state` function returns only the tools valid for the current state. This connects directly to the [Policy Engine](./policy-engine.md): the policy engine's per-tool allowlist is one layer; state-scoped filtering is a second, orthogonal layer. Together they answer both "is this tool ever permitted?" (policy engine) and "is this tool permitted *right now*?" (state machine).

```
  tool call requested by model
           │
           ▼
  ┌─────────────────────────┐
  │  State machine filter   │  "Is this tool valid in GATHER_CONTEXT?"
  │  filter_tools_for_state │  → reject write_file in read-only states
  └──────────┬──────────────┘
             │ passes
             ▼
  ┌─────────────────────────┐
  │  Policy engine guard    │  "Is this bash command on the allowlist?"
  │  _execute_one_tool gate │  → reject destructive commands globally
  └──────────┬──────────────┘
             │ passes
             ▼
         execute tool
```

## Trade-offs

| | Benefit | Cost |
|---|---|---|
| **Predictability** | The agent follows a known sequence; logs show exactly which state it was in when it stopped | Some tasks don't fit the linear sequence (e.g., a refactor that needs interleaved read/edit/read cycles) |
| **Budget control** | Per-state limits prevent runaway exploration or test loops | Budgets are heuristic — a complex codebase may legitimately need more GATHER_CONTEXT iterations |
| **Tool scoping** | Read-only states physically cannot call write tools | Adds a filtering layer; bugs in the filter table cause confusing tool-not-found errors |
| **Debuggability** | State transitions are logged; a stuck run shows exactly where it stopped | State transition logic is a new surface to test and maintain |
| **Testability** | Each state's `can_handle` / filter logic is independently testable | You now need tests for the state machine itself |

The main risk is over-fitting the state sequence to one task type. A task that needs to re-read files after editing (e.g., verifying the edit took effect) bumps into GATHER_CONTEXT's read-only constraint mid-run. Mitigations: allow `read_file` in EDIT state (the table above does this), design FIX_ERRORS with `allowed_tools=None`, and wire an escape hatch that promotes to the next state early when the model signals it is done (rather than waiting for the budget to expire).

## Related

- [The Agent Loop](../architecture/the-agent-loop.md) — the existing phases A–E that the state machine formalizes.
- [Steering](../advanced/steering.md) — steering messages can trigger state transitions (e.g., a user interrupt promotes directly to REVIEW_DIFF).
- [Planner / Executor Split](./planner-executor.md) — PLAN and EDIT states map naturally onto separate planner and executor roles.
- [Policy Engine / Guards](./policy-engine.md) — state-scoped tool filtering is the dynamic complement to the policy engine's static allowlist.
