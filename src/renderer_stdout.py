# src/renderer_stdout.py

"""Default renderer: plain-text stdout.

Stdout carries only the model's streamed text. Tool lifecycle markers
(start / result / error) moved to loguru on stderr in Layer 12.5, so a
redirect like `> result.txt` captures pure model output and diagnostics
stay on the terminal. See logging_config.py and agent.py's logger calls.
"""


def emit(event: dict) -> None:
    t = event["type"]
    if t == "text_delta":
        print(event["delta"], end="", flush=True)
    elif t == "turn_end":
        print()  # newline after the streamed turn
    # tool_call_start / tool_call_end → logger.debug on stderr (agent.py)
    # agent_end: no output in stdout mode
