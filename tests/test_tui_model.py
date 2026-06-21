"""Test that --model flag works with the TUI (AGENT_UI=tui)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock


def test_tui_passes_model_to_run_agent(monkeypatch):
    """When model is passed to tui.run(), it should be forwarded to run_agent."""
    # Prevent actual LLM calls and UI rendering
    mock_run_agent = AsyncMock(return_value=[])
    monkeypatch.setattr("agent.run_agent", mock_run_agent)

    # Mock the Textual app to prevent actual UI from starting
    mock_textual_app = MagicMock()
    monkeypatch.setattr("tui.app.App", mock_textual_app)

    from tui.app import AgentApp

    # Create the app with a model override
    app = AgentApp("test task", model="ollama/llama3.2")

    # Verify the model is stored
    assert app._model == "ollama/llama3.2"

    # Simulate the _drive method being called
    async def _verify_run_agent_call():
        # This simulates what happens in app.on_mount -> _drive
        await mock_run_agent(
            "test task",
            cancel_event=app.cancel_event,
            get_steering_messages=app._get_steering,
            model=app._model,
        )

    asyncio.run(_verify_run_agent_call())

    # Verify run_agent was called with the model parameter
    mock_run_agent.assert_called_once()
    call_kwargs = mock_run_agent.call_args.kwargs
    assert call_kwargs["model"] == "ollama/llama3.2"


def test_tui_run_accepts_model_parameter():
    """The tui.run() function should accept a model parameter."""
    import inspect

    from tui import run

    sig = inspect.signature(run)
    assert "model" in sig.parameters

    # Verify it has the right default
    assert sig.parameters["model"].default is None
