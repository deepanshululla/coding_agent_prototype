"""Evaluator-optimizer (critic) architecture.

Quality over one-shot: produce an answer reactively, then have a *critic* model
call judge it. If the critic approves (its verdict starts with PASS) we are done;
otherwise its critique is fed back into a fresh reactive revision, and we judge
again — up to MAX_ROUNDS times. This trades extra model calls for a higher-
quality final answer.

The revise step re-runs reactively with the critique folded into the task. (An
alternative wiring would inject the critique through the steering seam mid-run;
re-running keeps each attempt's context clean and is easy to reason about.)
"""

from __future__ import annotations

import agent
from architecture import RunContext, get_architecture, register
from renderer import emit

# How many revision rounds to attempt before returning the best answer so far.
MAX_ROUNDS = 2

_CRITIC_PROMPT = (
    "You are a strict reviewer. Judge whether the answer fully and correctly "
    "addresses the task. Reply with exactly 'PASS' if it does; otherwise reply "
    "with a short, specific critique of what to fix.\n\n"
    "Task: {task}\n\nAnswer: {answer}"
)
_REVISE_PROMPT = (
    "Revise your answer to the task using the reviewer's critique.\n\n"
    "Task: {task}\n\nYour previous answer: {answer}\n\nReviewer critique: {critique}"
)


def _final_text(history: list[dict]) -> str:
    for message in reversed(history):
        if message.get("role") == "assistant" and isinstance(message.get("content"), str):
            return message["content"]
    return ""


def _passed(verdict: str) -> bool:
    return verdict.strip().upper().startswith("PASS")


@register("evaluator-optimizer")
class EvaluatorOptimizer:
    async def run(self, task: str, ctx: RunContext) -> list[dict]:
        reactive = get_architecture("reactive")

        answer = _final_text(await reactive.run(task, self._worker_ctx(ctx)))

        rounds = 0
        while rounds < MAX_ROUNDS:
            verdict = await self._critique(task, answer, ctx)
            if _passed(verdict):
                break
            revise_task = _REVISE_PROMPT.format(task=task, answer=answer, critique=verdict)
            answer = _final_text(await reactive.run(revise_task, self._worker_ctx(ctx)))
            rounds += 1

        emit({"type": "agent_end", "total_iterations": rounds, "status": "ok"})
        return [
            {"role": "user", "content": task},
            {"role": "assistant", "content": answer},
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

    async def _critique(self, task: str, answer: str, ctx: RunContext) -> str:
        messages = [{"role": "user", "content": _CRITIC_PROMPT.format(task=task, answer=answer)}]
        turn = await agent.stream_turn(messages, system_prompt=ctx.system_prompt, model=ctx.model)
        return turn.text
