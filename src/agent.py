from __future__ import annotations

from provider import stream_response

MAX_ITERATIONS = 30


async def run_agent(task: str) -> list[dict]:
    """Run the agent on task and return the final message history.

    Phase 3: text-only, no tools, but the model response is now streamed.
    The inner loop consumes OpenAI-format chunks from stream_response,
    accumulates the text fragments into one assistant message, and tracks
    finish_reason so the loop knows when the model is done talking.
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

            # Phase A: stream the model response, accumulating as we go.
            text_buf = ""
            finish_reason = None

            async for chunk in stream_response(
                messages=messages,
                system_prompt="You are a helpful coding assistant.",
            ):
                choice = chunk.choices[0]
                delta = choice.delta
                # Carry the last non-None finish_reason forward.
                finish_reason = choice.finish_reason or finish_reason

                if getattr(delta, "content", None):
                    text_buf += delta.content
                    print(delta.content, end="", flush=True)  # live output

            print()  # newline after the streamed turn

            # Phase B: append the assistant's reply to history.
            messages.append({"role": "assistant", "content": text_buf})

            # Phase C: stop check — no tools in this phase, so a text reply
            # always means we are done.
            has_more_tool_calls = False

        break  # outer loop: no follow-up support yet

    return messages
