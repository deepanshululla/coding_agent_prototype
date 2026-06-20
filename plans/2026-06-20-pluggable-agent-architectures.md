Status: not started

# Pluggable agent architectures — make the loop strategy a swappable component

## Goal

Turn the agent's control-flow strategy into a registered, swappable component so
today's single loop becomes one selectable architecture among several
(`reactive` default, `orchestrator-worker`, `evaluator-optimizer`,
`planner-executor`), chosen via `--architecture` / `AGENT_ARCHITECTURE`. The
public `run_agent(...)` API and all existing behavior stay unchanged when no
architecture is selected.

## Design

An **architecture** is a strategy object implementing a small Protocol:

```python
class AgentArchitecture(Protocol):
    name: str
    async def run(self, task: str, ctx: RunContext) -> list[dict]: ...
```

`RunContext` is a dataclass bundling the seams `run_agent` currently threads as
loose kwargs (system_prompt, pending_messages, cancel_event, before/after hooks,
model, get_steering_messages) plus a `depth` counter for recursion guards.
Architectures compose two **reusable primitives** extracted from today's loop —
`stream_turn` (stream one model turn → assistant msg + parsed tool calls) and
`execute_tools` (parallel dispatch) — so no architecture reimplements streaming
or dispatch.

**Hard constraint:** the test suite monkeypatches `agent.stream_response` and
`agent.emit` as module globals. The primitives that call those MUST stay in
`agent.py` and resolve the names at call time, so patching keeps working and all
203 tests pass untouched. Architectures delegate to `agent.stream_turn` /
`agent.execute_tools` rather than importing `stream_response` directly.

## Files changed

| File | Change |
|---|---|
| `src/architecture.py` | **New.** `AgentArchitecture` Protocol, `RunContext` dataclass, `ARCHITECTURES` registry, `register()` decorator, `get_architecture(name)` with unknown→`reactive` fallback + stderr warning (mirrors `get_theme`'s dark fallback). |
| `src/agent.py` | Extract `stream_turn(messages, ctx)` and `execute_tools(calls, ctx)` primitives from the current loop. Implement `ReactiveAgent` (today's two-loop logic, behavior-identical) and register it as `reactive`. `run_agent(...)` keeps its exact signature, gains a trailing `architecture: str | None = None` kwarg, builds a `RunContext`, resolves the architecture, and delegates. |
| `src/architectures/__init__.py` | **New package.** Imports the alternate submodules so importing it registers them. |
| `src/architectures/orchestrator_worker.py` | **New.** Decompose task → run one reactive worker sub-agent per subtask (each `run_agent` with scoped/isolated context, `depth+1`) → synthesize. Reuses concurrency + provider seams. |
| `src/architectures/evaluator_optimizer.py` | **New.** Wrap a reactive run, then a critic model pass; on failure, feed the critique back via the steering seam and re-run, up to a bounded number of rounds. |
| `src/architectures/planner_executor.py` | **New.** Planning model call emits a typed step list; execute each step (reactive) in order, threading prior results into context. |
| `src/config.py` | Add `ARCHITECTURE = os.environ.get("AGENT_ARCHITECTURE", "reactive")` next to `MODEL`. |
| `main.py` | Add `_extract_architecture(args)` mirroring `_extract_model`; thread the selected name into `run_agent(..., architecture=...)`. |
| `tests/test_architecture.py` | **New.** Registry register/resolve, unknown→reactive fallback + warning, `RunContext` defaults, `run_agent` default selects `reactive`. |
| `tests/test_orchestrator_worker.py` | **New.** Scripted decomposition + worker turns + synthesis; assert one worker sub-agent per subtask and a synthesized final message; recursion guard honored. |
| `tests/test_evaluator_optimizer.py` | **New.** Scripted bad answer → critique → fixed answer; assert the loop re-runs and stops when the critic passes (and at the round cap). |
| `tests/test_planner_executor.py` | **New.** Scripted plan → per-step execution; assert steps run in order and results accumulate. |
| `main.py` tests (existing `tests/test_*` for flags) | Add `_extract_architecture` parsing coverage alongside the `_extract_model` tests. |

## Order of operations

1. **Seam module + tests** — write `tests/test_architecture.py` (registry/RunContext/fallback) red, then `src/architecture.py` green. No agent changes yet.
2. **Extract primitives** — pull `stream_turn` + `execute_tools` out of `run_agent` in `agent.py` with no behavior change; run the full suite green (pure refactor, safety-netted by existing tests).
3. **ReactiveAgent + facade** — implement `ReactiveAgent` over the primitives, register as `reactive`, make `run_agent` build a `RunContext` and delegate (default → reactive). Full suite stays green; add the "default selects reactive" test.
4. **Selection wiring** — `config.ARCHITECTURE`, `_extract_architecture` in `main.py`, `architecture` kwarg on `run_agent`; tests for parsing + resolution.
5. **OrchestratorWorker** — red test, then implement; verify recursion guard + per-subtask worker.
6. **EvaluatorOptimizer** — red test, then implement; verify re-run + round cap.
7. **PlannerExecutor** — red test, then implement; verify ordered execution.
8. **Polish** — README run section gains the `AGENT_ARCHITECTURE` knob; `ruff`/`ty`/`pre-commit`/full `pytest` all green.

## Verification

- [ ] Tests added: `tests/test_architecture.py`, `tests/test_orchestrator_worker.py`, `tests/test_evaluator_optimizer.py`, `tests/test_planner_executor.py`; existing 203 still pass.
- [ ] `uv run pytest -q` green.
- [ ] `uv run ruff check . && uv run ruff format --check . && uv run ty check` clean; `uv run pre-commit run --all-files` passes.
- [ ] Smoke each architecture (needs an API key): `AGENT_ARCHITECTURE=<name> uv run main.py "<task>"` and `task agent -- "<task>"` / `task tui`.

## Notes / open questions

- **Registry stores instances** (architectures are stateless; all per-run state rides in `RunContext`). The `register` decorator instantiates on registration.
- **Import-cycle handling:** alternates import primitives from `agent`; `run_agent` imports the `architectures` package lazily (function-local import) before resolving, mirroring the repo's existing function-local-import style — breaks the cycle.
- **Recursion/budget guard:** `RunContext.depth` caps orchestrator nesting; consider also a max-subtasks / token budget. Worth a default cap (e.g. depth ≤ 2).
- **Optionally also expose `spawn_agent` as a tool** so a reactive run can fan out sub-agents directly — deferred; the OrchestratorWorker architecture covers the structured case first.
- **Token cost:** orchestrator/critic/planner all multiply model calls (2–3×+). Acceptable as opt-in; note it in the README.
- Architectures live in a `src/architectures/` package (vs flat modules) because there are 3+; `reactive` stays in `agent.py` as the canonical default.
