---
sidebar_position: 10
title: Planner / Executor Split
description: Separate "decide the plan" from "carry it out" so a human or policy can review the plan before any file is touched.
---

# Planner / Executor Split

One `run_agent` call does everything: decides what files to touch, touches them, checks the result, and keeps going. That works for small tasks. For anything longer — refactoring a module, upgrading a dependency across a monorepo, applying a multi-file architectural change — the lack of separation becomes a problem.

The Planner / Executor split cuts the work into two distinct roles:

- **Planner**: reads the codebase, reasons about the task, and produces a structured *plan* — steps, files to touch, success criteria. It makes no edits.
- **Executor**: walks the plan one step at a time, calling write/edit/bash tools, and reports progress back.

The plan is the artifact that makes everything else tractable: it can be approved, logged, re-read after a failure, and used as a checkpoint for retries.

:::note Design guidance
This page describes a recommended pattern for when you outgrow the v1 loop. The shipped `src/agent.py` is a single unified loop — there is no planner/executor split today. The seam where this pattern slots in is `run_agent` in `src/agent.py`.
:::

## The problem

The v1 inner loop in `src/agent.py` runs for up to `MAX_ITERATIONS = 30` cycles. The model decides what to do at each step based only on the messages so far. That means:

- **No reviewability.** You cannot see or approve the agent's intentions before edits start. By the time you notice a bad direction, several files have already changed.
- **No checkpointing.** If the agent hits an error mid-way through a 15-step task, it restarts from the beginning and re-derives the plan at iteration cost.
- **Weak long-horizon behavior.** Without an explicit plan to follow, the model can drift — completing an early step in a way that makes a later step harder, or forgetting what it set out to do after a long tool-call chain.
- **No policy hook.** You cannot ask "is this plan acceptable?" before any I/O happens, which is exactly what the [policy engine](./policy-engine.md) needs.

## The pattern

Split `run_agent` into two phases:

```
task
  │
  ▼
┌─────────────────────────────┐
│  PLANNER  (read-only tools) │
│  → returns a Plan object    │
└──────────────┬──────────────┘
               │ optional: human or policy approves here
               ▼
┌─────────────────────────────┐
│  EXECUTOR  (write + bash)   │
│  → one step at a time       │
│  → reports back per step    │
└─────────────────────────────┘
```

**The Planner** is a `run_agent` call restricted to read-only tools (`read_file`, `grep`, `find_files`, `list_dir`). Its system prompt asks for a structured plan — not code changes. It exits when it returns a `Plan` object in its final message.

**The Executor** receives that plan and works through it step by step, using write/edit/bash tools. It reports its result for each step before moving to the next. If a step fails, it can replan (call the Planner again with the failure context) or surface the failure for human input — see [Steering](../advanced/steering.md).

The **plan itself** is a structured artifact that sits between the two phases:

```python
from dataclasses import dataclass, field

@dataclass
class PlanStep:
    id: str                    # e.g. "step-1"
    description: str           # human-readable: "Add type hint to read_file"
    files: list[str]           # files this step will touch
    success_criterion: str     # how to verify the step is done

@dataclass
class Plan:
    task: str
    steps: list[PlanStep]
    notes: str = ""            # anything the planner wants the executor to know
```

## In this project

The natural seam is `run_agent` in `src/agent.py`. Today it looks like this (simplified):

```python
async def run_agent(task: str) -> list[dict]:
    messages = [{"role": "user", "content": task}]
    # ... one loop that both decides and acts
```

With the split, you wrap that into two calls:

```python
# ── Restricted tool set for the planner ──────────────────────────────────────

READ_ONLY_TOOLS = {"read_file", "grep", "find_files", "list_dir"}

READ_ONLY_SCHEMA = [
    schema for schema in TOOLS_SCHEMA
    if schema["function"]["name"] in READ_ONLY_TOOLS
]

READ_ONLY_REGISTRY = {
    name: fn
    for name, fn in TOOL_REGISTRY.items()
    if name in READ_ONLY_TOOLS
}

# ── Planner: no writes, returns a Plan ───────────────────────────────────────

async def run_planner(task: str) -> Plan:
    """Run the agent with read-only tools; expect the final message to be a Plan JSON."""
    system_prompt = build_planner_prompt()   # asks for structured Plan output
    messages: list[dict] = [{"role": "user", "content": task}]

    # Same inner loop as run_agent, but uses READ_ONLY_SCHEMA / READ_ONLY_REGISTRY.
    # When finish_reason == "stop" and no tool calls, parse the last assistant message.
    final_messages = await _run_loop(
        messages, system_prompt,
        tool_schema=READ_ONLY_SCHEMA,
        tool_registry=READ_ONLY_REGISTRY,
    )
    last = final_messages[-1]["content"]
    return Plan(**json.loads(last))   # planner emits JSON matching Plan schema

# ── Executor: works through the plan one step at a time ──────────────────────

async def run_executor(plan: Plan) -> list[dict]:
    """Execute each PlanStep in order, using the full tool set."""
    system_prompt = build_executor_prompt(plan)
    messages: list[dict] = []

    for step in plan.steps:
        messages.append({"role": "user", "content": f"Execute: {step.description}"})
        messages = await _run_loop(
            messages, system_prompt,
            tool_schema=TOOLS_SCHEMA,
            tool_registry=TOOL_REGISTRY,
        )
        # Check step.success_criterion; replan or surface failure as needed.

    return messages

# ── Top-level orchestrator ────────────────────────────────────────────────────

async def run_agent_with_planning(task: str, approve: bool = False) -> list[dict]:
    plan = await run_planner(task)

    if approve:
        # Gate: show the plan, wait for a human "yes" before any write happens.
        # This is the policy engine hook — see policy-engine.md.
        print(plan)
        input("Press Enter to approve, Ctrl-C to abort: ")

    return await run_executor(plan)
```

The `_run_loop` helper is the existing inner loop from `run_agent`, extracted to accept a `tool_schema` and `tool_registry` argument — roughly a 5-line change to the current code.

### The plan-approval gate

The `approve=True` path in `run_agent_with_planning` is where the [policy engine](./policy-engine.md) plugs in. Instead of a plain `input()`, the policy engine inspects the plan and makes a deterministic decision:

```python
async def policy_gate(plan: Plan) -> bool:
    """Return True if this plan is allowed to proceed without human approval."""
    for step in plan.steps:
        for f in step.files:
            if is_sensitive_path(f):          # policy: never auto-touch .env, secrets/
                return False                  # require human review
    return True                               # all steps look safe
```

This cleanly separates "should we run?" (deterministic, policy-enforced) from "what should we run?" (LLM-generated).

### Permission modes

The [permission modes](./permission-modes.md) map directly onto the planner/executor split:

| Mode | Planner | Executor |
|---|---|---|
| `read-only` | Runs normally | Blocked — no writes |
| `ask` | Runs normally; plan is shown and must be approved | Runs only after approval |
| `auto` | Runs normally | Runs without interruption |

### Replanning on failure

When an executor step fails, the agent can re-invoke the planner with the failure context appended to the messages. This is the replanning hook described in [Steering](../advanced/steering.md):

```python
# Inside run_executor, after a step fails:
plan = await run_planner(
    f"Original task: {plan.task}\n\n"
    f"Step '{step.id}' failed: {failure_reason}\n\n"
    "Please revise the plan."
)
```

The plan becomes a checkpoint: failed steps are known, completed steps are recorded in the executor's message history, and the new plan picks up from where things went wrong. Without an explicit plan, replanning means restarting the entire task from scratch — expensive and often incomplete.

### Connecting to context compaction

Long-running executors accumulate large message histories. The plan acts as a natural compaction boundary: when history grows unwieldy, you can summarize completed steps and retain only the plan + recent context, as described in [Compaction](../advanced/compaction.md). The plan is the anchor that makes the summary coherent.

## Trade-offs

| | Without split | With split |
|---|---|---|
| **Reviewability** | No plan to inspect before edits | Plan is an explicit artifact — show, log, or approve it |
| **Long-horizon reliability** | Model can drift across 30 iterations | Executor follows a fixed plan; drift is bounded to individual steps |
| **Checkpoint / retry** | Restart from scratch on failure | Resume from the failed step; replan with context |
| **Policy hook** | Hard to gate before any I/O | Plan approval is a clean policy seam |
| **Complexity** | Single function, ~130 lines | Two phases, a shared `_run_loop`, a `Plan` dataclass |
| **Latency** | One model call sequence | Two sequential call sequences before work begins |
| **Short tasks** | Efficient — no overhead | Planning call is wasted if the task is one edit |

The split pays off when tasks span multiple files, when you need a human in the loop, or when reliability under failure matters. For quick single-file edits, the unified loop is fine.

## Related

- [State Machine](./state-machine.md) — make the executor phases (GATHER → PLAN → EDIT → TEST → DONE) explicit states rather than implicit LLM decisions
- [Policy Engine](./policy-engine.md) — the deterministic gate that sits at the plan-approval seam
- [Permission Modes](./permission-modes.md) — read-only / ask / auto map cleanly onto planner and executor phases
- [Steering](../advanced/steering.md) — how follow-up messages and replanning feed back into a running agent
- [Compaction](../advanced/compaction.md) — using the plan as a compaction anchor for long executor runs
