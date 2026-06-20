"""Unit tests for the pluggable-architecture seam.

Covers the registry mechanics (register / resolve / unknown-fallback) and the
RunContext defaults. Architecture *behaviors* live in their own test modules;
here we only exercise the seam in src/architecture.py.
"""

import asyncio

import pytest

import architecture
from architecture import (
    ARCHITECTURES,
    DEFAULT_ARCHITECTURE,
    RunContext,
    get_architecture,
    register,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Snapshot and restore ARCHITECTURES so tests can register freely without
    clobbering the real architectures other test modules rely on."""
    snapshot = dict(architecture.ARCHITECTURES)
    yield
    ARCHITECTURES.clear()
    ARCHITECTURES.update(snapshot)


def test_register_instantiates_and_resolves():
    @register("stub_test")
    class StubArch:
        async def run(self, task, ctx):
            return [{"role": "assistant", "content": "stub"}]

    arch = get_architecture("stub_test")
    assert ARCHITECTURES["stub_test"] is arch
    assert isinstance(arch, StubArch)
    # The decorator sets .name from the registry key.
    assert arch.name == "stub_test"


def test_unknown_name_falls_back_to_default_with_warning(capsys):
    @register(DEFAULT_ARCHITECTURE)
    class DefaultArch:
        async def run(self, task, ctx):
            return []

    arch = get_architecture("does_not_exist")
    assert arch.name == DEFAULT_ARCHITECTURE
    err = capsys.readouterr().err
    assert "does_not_exist" in err


def test_none_resolves_to_default_without_warning(capsys):
    @register(DEFAULT_ARCHITECTURE)
    class DefaultArch:
        async def run(self, task, ctx):
            return []

    arch = get_architecture(None)
    assert arch.name == DEFAULT_ARCHITECTURE
    assert capsys.readouterr().err == ""


def test_runcontext_defaults():
    ctx = RunContext(system_prompt="hi")
    assert ctx.system_prompt == "hi"
    assert ctx.pending_messages == []
    assert ctx.cancel_event is None
    assert ctx.before_tool_call is None
    assert ctx.after_tool_call is None
    assert ctx.model is None
    assert ctx.get_steering_messages is None
    assert ctx.depth == 0


def test_runcontext_pending_messages_are_independent():
    """Each RunContext gets its own list (no shared mutable default)."""
    a = RunContext(system_prompt="x")
    b = RunContext(system_prompt="y")
    a.pending_messages.append({"role": "user", "content": "hi"})
    assert b.pending_messages == []


def test_importing_agent_registers_reactive_as_default():
    """agent.py registers ReactiveAgent under the default name at import time, so
    run_agent with no architecture resolves to it."""
    import agent  # noqa: F401 — import side effect registers "reactive"

    assert DEFAULT_ARCHITECTURE in ARCHITECTURES
    assert type(get_architecture(None)).__name__ == "ReactiveAgent"


def test_run_agent_delegates_to_selected_architecture():
    """run_agent(architecture=name) routes to that architecture, passing the task
    and a RunContext carrying the seams — proving the loop is now pluggable."""
    import agent

    seen = {}

    @register("recording_arch")
    class Recording:
        async def run(self, task, ctx):
            seen["task"] = task
            seen["system_prompt"] = ctx.system_prompt
            return [{"role": "assistant", "content": "recorded"}]

    out = asyncio.run(
        agent.run_agent("do the thing", architecture="recording_arch", system_prompt="SP")
    )
    assert seen == {"task": "do the thing", "system_prompt": "SP"}
    assert out == [{"role": "assistant", "content": "recorded"}]
