"""Planner-executor architecture.

Plan first, then act: one planning model call lays out an ordered list of steps,
then each step runs reactively *in sequence*, with the results of earlier steps
threaded into the next step's context. Unlike the orchestrator's independent
subtasks, these steps are dependent — the final answer is the last step's
result. Good for long, predictable workflows where the shape is known up front.
"""

from __future__ import annotations

import agent
from architecture import RunContext, get_architecture, register
from logging_config import logger
from renderer import emit

MAX_STEPS = 8  # cap the plan length

_PLAN_PROMPT = (
    "Produce an ordered, numbered plan of concrete steps to accomplish the task, "
    "one step per line, no commentary. If the task needs no planning, return it "
    "as a single line.\n\nTask: {task}"
)
_STEP_PROMPT = (
    "{step}\n\nThis is part of the larger task: {task}\n\nResults of earlier steps:\n{prior}"
)


def _parse_steps(text: str) -> list[str]:
    steps: list[str] = []
    for line in text.splitlines():
        cleaned = line.strip().lstrip("-*0123456789.) ").strip()
        if cleaned:
            steps.append(cleaned)
    return steps


def _final_text(history: list[dict]) -> str:
    for message in reversed(history):
        if message.get("role") == "assistant" and isinstance(message.get("content"), str):
            return message["content"]
    return ""


@register("planner-executor")
class PlannerExecutor:
    async def run(self, task: str, ctx: RunContext) -> list[dict]:
        reactive = get_architecture("reactive")

        steps = _parse_steps(await self._plan(task, ctx))
        if not steps:
            return await reactive.run(task, ctx)
        if len(steps) > MAX_STEPS:
            logger.info("capping {} steps to {}", len(steps), MAX_STEPS)
            steps = steps[:MAX_STEPS]

        results: list[tuple[str, str]] = []
        for step in steps:
            # First step has no prior context; later steps see earlier results.
            if results:
                prior = "\n\n".join(f"{s}: {r}" for s, r in results)
                step_task = _STEP_PROMPT.format(step=step, task=task, prior=prior)
            else:
                step_task = step
            history = await reactive.run(step_task, self._worker_ctx(ctx))
            results.append((step, _final_text(history)))

        emit({"type": "agent_end", "total_iterations": len(steps), "status": "ok"})
        return [
            {"role": "user", "content": task},
            {"role": "assistant", "content": results[-1][1]},
        ]

    def _worker_ctx(self, ctx: RunContext) -> RunContext:
        return RunContext(
            system_prompt=ctx.system_prompt,
            cancel_event=ctx.cancel_event,
            before_tool_call=ctx.before_tool_call,
            after_tool_call=ctx.after_tool_call,
            model=ctx.model,
            depth=ctx.depth + 1,
        )

    async def _plan(self, task: str, ctx: RunContext) -> str:
        messages = [{"role": "user", "content": _PLAN_PROMPT.format(task=task)}]
        turn = await agent.stream_turn(messages, system_prompt=ctx.system_prompt, model=ctx.model)
        return turn.text
