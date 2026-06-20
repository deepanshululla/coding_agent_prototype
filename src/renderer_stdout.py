# src/renderer_stdout.py

"""Default renderer: plain-text stdout.

Reproduces the original print() output exactly so AGENT_UI=stdout (the
default) is a no-op change from the caller's point of view.
"""


def emit(event: dict) -> None:
    t = event["type"]
    if t == "text_delta":
        print(event["delta"], end="", flush=True)
    elif t == "tool_call_start":
        print(f"\n▸ {event['name']}", end="", flush=True)
    elif t == "tool_call_end":
        status = "✓" if not event["is_error"] else "✗"
        print(f"  [{status} {event['name']}: {event['chars']} chars]")
    elif t == "turn_end":
        print()  # newline after the streamed turn
    # agent_end: no output in stdout mode
