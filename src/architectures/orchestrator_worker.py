"""Orchestrator-worker architecture.

Instead of one long reactive loop, the orchestrator splits the task into
subtasks, runs an isolated reactive *worker* for each (fresh context, so a noisy
subtask never pollutes the others' windows), then makes one final model call to
synthesize the workers' results into a single answer.

Three kinds of model call, in order: decompose → one reactive run per subtask →
synthesize. Workers run at depth+1; past MAX_DEPTH the orchestrator stops
decomposing and just runs the task reactively, so nesting can't run away.
"""

from __future__ import annotations

import agent
from architecture import RunContext, get_architecture, register
from logging_config import logger
from renderer import emit

# Cap orchestrator nesting and the per-task subtask fan-out.
MAX_DEPTH = 2
MAX_SUBTASKS = 5

_DECOMPOSE_PROMPT = (
    "Break the following task into a short ordered list of independent "
    "subtasks, one per line, no commentary. If it is already atomic, return it "
    "as a single line.\n\nTask: {task}"
)
_SYNTHESIZE_PROMPT = (
    "You delegated subtasks to workers. Using their results below, write the "
    "final answer to the original task.\n\nOriginal task: {task}\n\n{results}"
)


def _parse_subtasks(text: str) -> list[str]:
    """Turn the decomposition text into a clean subtask list.

    Strips common list prefixes (``1.``, ``-``, ``*``) and drops blank lines.
    """
    subtasks: list[str] = []
    for line in text.splitlines():
        cleaned = line.strip().lstrip("-*0123456789.) ").strip()
        if cleaned:
            subtasks.append(cleaned)
    return subtasks


def _final_text(history: list[dict]) -> str:
    """The worker's answer: the last assistant message with plain-string content."""
    for message in reversed(history):
        if message.get("role") == "assistant" and isinstance(message.get("content"), str):
            return message["content"]
    return ""


@register("orchestrator-worker")
class OrchestratorWorker:
    async def run(self, task: str, ctx: RunContext) -> list[dict]:
        reactive = get_architecture("reactive")

        # Recursion guard: too deep to keep delegating — just do the work.
        if ctx.depth >= MAX_DEPTH:
            logger.debug("orchestrator at depth {}, running reactively", ctx.depth)
            return await reactive.run(task, ctx)

        subtasks = _parse_subtasks(await self._decompose(task, ctx))
        if len(subtasks) <= 1:
            # Nothing to gain from a single-worker fan-out + synthesis.
            return await reactive.run(task, ctx)
        if len(subtasks) > MAX_SUBTASKS:
            logger.info("capping {} subtasks to {}", len(subtasks), MAX_SUBTASKS)
            subtasks = subtasks[:MAX_SUBTASKS]

        results: list[tuple[str, str]] = []
        for subtask in subtasks:
            history = await reactive.run(subtask, self._worker_ctx(ctx))
            results.append((subtask, _final_text(history)))

        final = await self._synthesize(task, results, ctx)
        emit({"type": "agent_end", "total_iterations": len(subtasks), "status": "ok"})
        return [
            {"role": "user", "content": task},
            {"role": "assistant", "content": final},
        ]

    def _worker_ctx(self, ctx: RunContext) -> RunContext:
        """A fresh context for a worker: isolated history, no steering, depth+1."""
        return RunContext(
            system_prompt=ctx.system_prompt,
            cancel_event=ctx.cancel_event,
            before_tool_call=ctx.before_tool_call,
            after_tool_call=ctx.after_tool_call,
            model=ctx.model,
            depth=ctx.depth + 1,
        )

    async def _decompose(self, task: str, ctx: RunContext) -> str:
        messages = [{"role": "user", "content": _DECOMPOSE_PROMPT.format(task=task)}]
        turn = await agent.stream_turn(messages, system_prompt=ctx.system_prompt, model=ctx.model)
        return turn.text

    async def _synthesize(self, task: str, results: list[tuple[str, str]], ctx: RunContext) -> str:
        joined = "\n\n".join(f"Subtask: {sub}\nResult: {res}" for sub, res in results)
        messages = [
            {"role": "user", "content": _SYNTHESIZE_PROMPT.format(task=task, results=joined)}
        ]
        turn = await agent.stream_turn(messages, system_prompt=ctx.system_prompt, model=ctx.model)
        return turn.text
