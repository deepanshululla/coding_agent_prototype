"""Phase 12.1 — The Security Model (BDD red-line gate).

This module has NO src/ build output. The "build" for this layer is understanding
the threat model well enough to express it as an executable scenario. The scenario
below proves — against the unguarded Phase 11 agent — that a destructive command is
dispatched and executed with no allowlist check and no permission prompt.

The three threat categories this layer establishes (see
website/docs/tutorial/12-harden-it/1-security-model.md):

  1. Destructive commands — bash runs ``subprocess.run(command, shell=True)`` with
     no allowlist and no approval. The model decides; the agent executes.
  2. Prompt injection via tool content — a malicious file/command output can carry
     instructions that hijack the session mid-chain.
  3. Secret exfiltration — ANTHROPIC_API_KEY lives in the process env and is
     reachable via ``echo $ANTHROPIC_API_KEY`` through bash.

Recommended operating posture until Layers 12.2–12.5 land (recorded here as the
acceptance context for this gate):

  1. Run the agent only against repositories you own and have reviewed.
  2. Work in a git repository so every change is reversible.
  3. Do not expose unrelated secrets (DB passwords, deploy keys) in the agent's env.
  4. Never point the agent at untrusted content (cloned repos, user-submitted files).

The built-in limits are reliability controls, NOT security controls:

  * BASH_TIMEOUT (30s) caps runaway commands so the loop is not blocked — a
    ``rm -rf /`` finishes well inside 30s, so this does not protect anything.
  * BASH_OUTPUT_LIMIT (10,000 chars) keeps a tool result from flooding the
    context window — 10k chars is more than enough to exfiltrate any secret.
  * MAX_ITERATIONS (30) prevents infinite looping — 30 turns is plenty to do
    real damage.

Each of these reduces the *window* for mischief but stops nothing. The actual
controls (allowlist, permission mode, sandboxing) arrive in Layers 12.2–12.5.

Layer 12.2 has now added the default-deny allowlist, so this scenario has FLIPPED:
``rm`` is not allowlisted, so the command is refused with a
``ToolResult(is_error=True)`` *before* execution. The test below is kept as the
historical red-line context in its flipped (post-12.2) form — it now proves the
gate blocks the destructive command instead of executing it.
"""

from __future__ import annotations

import asyncio

import agent
import tools
from provider import _chunk, _tc


class ScriptedLLM:
    """Stand-in for stream_response: yields pre-built chunks, one turn per call.

    Mirrors the harness in tests/test_agent.py so the real agent loop runs
    unmodified — only the model is scripted.
    """

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


def test_allowlist_gate_refuses_destructive_command(monkeypatch):
    """Scenario: After Layer 12.2 the allowlist refuses a destructive command.

    Given the agent with the command allowlist gate installed in _execute_one_tool
    And "rm" is not in the allowed programs list
    When the agent is given the task
         "delete all .pyc files by running: rm -rf __pycache__"
    Then the agent requests bash with command "rm -rf __pycache__"
    And _execute_one_tool returns a ToolResult with is_error=True
    And the ToolResult content contains "not an allowed command"
    And the bash tool function is never called

    This is the flipped form of the Phase 12.1 red-line scenario: before the
    Layer 12.2 gate the unguarded agent executed ``rm`` outright; with the gate
    installed the command is refused *before* dispatch. We stub ``tools.bash``
    to record any invocation, so the test proves the function is never reached.
    """
    destructive_cmd = "rm -rf __pycache__"
    executed: list[str] = []

    async def fake_bash(command: str) -> str:
        # If this records anything, the gate failed to block the command.
        executed.append(command)
        return "(exit code 0)\n"

    monkeypatch.setitem(tools.TOOL_REGISTRY, "bash", fake_bash)

    # Turn 1: model emits a single bash tool call carrying the destructive command.
    # Turn 2: model produces a plain-text turn, ending the loop.
    turns = [
        [
            _chunk(
                tool_calls=[
                    _tc(index=0, id="call_rm", name="bash"),
                    _tc(
                        index=0,
                        arguments=f'{{"command": "{destructive_cmd}"}}',
                    ),
                ]
            ),
            _chunk(finish_reason="tool_calls"),
        ],
        [
            _chunk(content="Done."),
            _chunk(finish_reason="stop"),
        ],
    ]
    monkeypatch.setattr(agent, "stream_response", ScriptedLLM(turns))

    messages = asyncio.run(agent.run_agent("delete all .pyc files by running: rm -rf __pycache__"))

    # Then: the bash function was never called — the gate refused before dispatch.
    assert executed == []

    # And: an is_error tool result was injected, carrying the refusal reason.
    tool_messages = [m for m in messages if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert "not an allowed command" in tool_messages[0]["content"]
