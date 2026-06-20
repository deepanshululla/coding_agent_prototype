from __future__ import annotations

import provider

MAX_ITERATIONS = 30


async def run_agent(task: str) -> list[dict]:
    """Run the agent on task and return the final message history.

    Phase 2: text-only, no tools. The loop calls the model, appends the
    assistant reply, and stops when the model returns plain text (no tool
    calls to make).
    """
    messages: list[dict] = [{"role": "user", "content": task}]

    # OUTER LOOP: re-enters if follow-up messages arrive.
    # In this phase it runs exactly once.
    while True:
        has_more_tool_calls = True
        iteration = 0

        # INNER LOOP: the tool-call cycle.
        while has_more_tool_calls and iteration < MAX_ITERATIONS:
            iteration += 1

            # Phase A: ask the model
            reply_text = await provider.call_model(
                messages=messages,
                system_prompt="You are a helpful coding assistant.",
            )

            # Phase B: append the assistant's reply to history
            messages.append({"role": "assistant", "content": reply_text})

            # Phase C: stop check — no tools in this phase, so a text reply
            # always means we are done.
            has_more_tool_calls = False

        break  # outer loop: no follow-up support yet

    return messages
