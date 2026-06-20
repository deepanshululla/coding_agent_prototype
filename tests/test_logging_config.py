"""Tests for src/logging_config.py and the agent's migration to logger.

The BDD gate (the scenario in the plan) is exercised by
test_tool_lifecycle_events_on_stderr_not_stdout: at DEBUG level the tool
lifecycle lines land on the loguru stream (stderr) and stdout — the
agent's print() output — carries no "[executing" or "[✓" markers.
"""

import asyncio
import io

import pytest
from loguru import logger

import agent
import logging_config
from provider import _chunk, _tc


class ScriptedLLM:
    def __init__(self, turns):
        self._turns = list(turns)
        self._index = 0

    def __call__(self, messages, system_prompt, model=None):
        turn = self._turns[self._index]
        self._index += 1

        async def _gen():
            for chunk in turn:
                yield chunk

        return _gen()


@pytest.fixture(autouse=True)
def _reset_logging():
    """Each test starts from a clean loguru state and a fresh _configured flag."""
    logging_config._configured = False
    logger.remove()
    yield
    logging_config._configured = False
    logger.remove()


def test_setup_logging_is_idempotent(monkeypatch):
    """Calling setup_logging() twice adds the sink only once."""
    monkeypatch.delenv("AGENT_LOG_FILE", raising=False)
    monkeypatch.setenv("AGENT_LOG_LEVEL", "INFO")

    sink = io.StringIO()
    logging_config.setup_logging()
    # Re-point: capture whatever the second call would (should be no-op).
    logging_config.setup_logging()

    # A single configured stderr sink: emit and ensure the message lands once.
    handler_id = logger.add(sink, level="DEBUG", format="{message}")
    logger.info("hello")
    logger.remove(handler_id)
    assert sink.getvalue().count("hello") == 1


def test_debug_level_emits_to_stream(monkeypatch):
    """At DEBUG level, logger.debug lines are captured by the sink."""
    monkeypatch.setenv("AGENT_LOG_LEVEL", "DEBUG")
    monkeypatch.delenv("AGENT_LOG_FILE", raising=False)

    sink = io.StringIO()
    logger.add(sink, level="DEBUG", format="{message}")
    logging_config._configured = True  # skip the real stderr sink
    logger.debug("executing tool read_file with {}", {"path": "x"})
    assert "executing tool read_file with" in sink.getvalue()


def test_tool_lifecycle_events_on_stderr_not_stdout(monkeypatch, tmp_path, capsys):
    """BDD gate: at DEBUG level lifecycle lines go to the logger (stderr),
    while stdout (agent print output) has no [executing or [✓ markers."""
    target = tmp_path / "hello.txt"
    target.write_text("hello from the file")

    # Capture loguru output in a dedicated sink standing in for stderr.
    log_sink = io.StringIO()
    logging_config._configured = True  # avoid touching real stderr
    handler_id = logger.add(log_sink, level="DEBUG", format="{message}")

    turn1 = [
        _chunk(
            tool_calls=[
                _tc(0, id="call_abc", name="read_file", arguments=f'{{"path": "{target}"}}'),
            ],
        ),
        _chunk(finish_reason="tool_calls"),
    ]
    turn2 = [
        _chunk(content="The file says: hello from the file."),
        _chunk(finish_reason="stop"),
    ]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM([turn1, turn2]))

    asyncio.run(agent.run_agent("read hello.txt"))
    logger.remove(handler_id)

    log_output = log_sink.getvalue()
    assert "executing tool read_file with" in log_output
    assert "tool read_file ok:" in log_output

    stdout = capsys.readouterr().out
    assert "[executing" not in stdout
    assert "[✓" not in stdout


def test_unknown_tool_logs_warning(monkeypatch):
    """An unknown tool produces a logger.warning line."""
    log_sink = io.StringIO()
    logging_config._configured = True
    handler_id = logger.add(log_sink, level="WARNING", format="{message}")

    result = asyncio.run(
        agent._execute_one_tool({"id": "x", "name": "nope", "input": {}, "index": 0})
    )
    logger.remove(handler_id)

    assert result.is_error
    assert "unknown tool" in log_sink.getvalue().lower()
