import inspect

import provider


def test_stream_response_is_async_generator():
    """stream_response must be an async generator function — the loop depends on it.

    The backend swapped from `claude -p` to litellm.acompletion in Phase 11, but
    the signature contract is unchanged: stream_response stays an async generator
    yielding OpenAI-format chunks, so the agent loop never changes.
    """
    assert inspect.isasyncgenfunction(provider.stream_response)
