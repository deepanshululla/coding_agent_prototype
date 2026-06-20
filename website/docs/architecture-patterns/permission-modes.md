---
sidebar_position: 12
title: Permission Modes
description: One environment-variable switch — AGENT_PERMISSION_MODE — that controls whether the agent runs read-only, prompts before dangerous actions, or executes autonomously, and how it interacts with the policy engine and plugin permission levels.
---

# Permission Modes

A single switch governs how the agent treats every tool call: read-only, ask before dangerous
actions, or auto-execute within the allowlist. This switch — `AGENT_PERMISSION_MODE` — sits
above the [policy engine](./policy-engine.md) and controls its default behavior without
changing any rule.

:::note Design guidance, not v1
The shipped core has no permission mode switch. `_execute_one_tool` in `src/agent.py` dispatches
every tool call immediately. This page describes how to add the mode switch as a thin layer over
the [Policy Engine](./policy-engine.md). Add it when you need to run the agent in different
postures for different tasks (exploration vs. automation vs. locked-down CI).
:::

## The problem

The right level of autonomy depends on context:

- **Exploring an unfamiliar codebase** — you want the agent to read freely but stop before
  touching anything.
- **Interactive development** — the agent can patch files and run tests, but you want to
  approve each shell command.
- **CI / automated pipeline** — the agent runs unattended; only allowlisted commands are
  permitted, no interactive prompts.

Hard-coding any one posture into the agent loop means re-editing code for every context switch.
A mode switch externalizes the posture as configuration.

## The modes

Three modes cover the main operating postures:

| Mode | `AGENT_PERMISSION_MODE` value | What it does |
|---|---|---|
| Read-only | `read-only` | All write and execute tools (`bash`, `write_file`, `edit_file`) are denied before dispatch. Read tools (`read_file`, `grep`, `find_files`, `list_dir`) run freely. |
| Ask | `ask` | Read tools run freely. Dangerous tools prompt the user for approval before each call. Allowlisted commands may run without prompting (configurable). |
| Auto | `auto` | Read tools run freely. Commands that pass the [command allowlist](../operations/command-allowlist.md) run without prompting. Commands not on the allowlist prompt the user. |

A fourth mode is sometimes useful:

| Mode | Value | What it does |
|---|---|---|
| Plan-only | `plan` | Like read-only, but the agent may also emit structured plan output. No writes or executes are dispatched. |

## How the mode feeds into the policy engine

The mode is the input to `PolicyEngine.from_env()`. It selects the rule set and the engine's
**default outcome** — what happens when no rule matches:

```python
# src/policy.py (planned extension)
import os

def build_engine() -> PolicyEngine:
    mode = os.environ.get("AGENT_PERMISSION_MODE", "ask")

    if mode == "read-only":
        return PolicyEngine(
            rules=[ReadOnlyRule(), SecretGuardRule()],
            default="deny",
        )

    if mode == "auto":
        return PolicyEngine(
            rules=[
                SecretGuardRule(),
                CommandAllowlistRule(),   # allow if on allowlist, deny if not
                PathRestrictionRule(allowed_root=os.getcwd()),
                PluginPermissionRule(plugin_levels=_load_plugin_levels(), mode="auto"),
            ],
            default="deny",   # auto still denies unknown tools; allowlist is the gate
        )

    # mode == "ask" (default)
    return PolicyEngine(
        rules=[
            SecretGuardRule(),            # always deny secret reads
            CommandAllowlistRule(),       # allow safe commands without prompting
            PathRestrictionRule(allowed_root=os.getcwd()),
            PluginPermissionRule(plugin_levels=_load_plugin_levels(), mode="ask"),
        ],
        default="ask",    # anything that doesn't match a rule goes to the user
    )
```

The mode is read once at startup, not per-call. The agent instance carries the configured
engine through its entire run.

## Tool behavior by mode

This table covers all 7 tools across the 3 main modes.
"Auto-allow" means the tool dispatches immediately. "Deny" returns `ToolResult(is_error=True)`
to the model. "Prompt" pauses to ask the user.

| Tool | Read-only | Ask | Auto |
|---|---|---|---|
| `read_file` | Auto-allow | Auto-allow | Auto-allow |
| `grep` | Auto-allow | Auto-allow | Auto-allow |
| `find_files` | Auto-allow | Auto-allow | Auto-allow |
| `list_dir` | Auto-allow | Auto-allow | Auto-allow |
| `bash` | Deny | Prompt (unless allowlisted) | Allow if allowlisted; deny otherwise |
| `write_file` | Deny | Prompt | Prompt (path-checked; outside root → deny) |
| `edit_file` | Deny | Prompt | Prompt (path-checked; outside root → deny) |

:::tip Auto mode still gates on the allowlist
"Auto" does not mean "run anything". `bash` calls in auto mode are checked against the
[command allowlist](../operations/command-allowlist.md) — if the command isn't on the list it
is denied (not prompted), so the model must use an allowed command or ask the user to widen the
allowlist. This makes auto mode safe for CI.
:::

## Plugin `permission_level`

Plugins (tools added via the [plugin architecture](./plugin-architecture.md)) declare their own
`permission_level` in their tool descriptor:

```python
# A plugin tool descriptor (planned extension)
{
    "name": "deploy_to_staging",
    "permission_level": "dangerous",   # "safe" | "dangerous" | "restricted"
    "description": "Run a deployment pipeline to the staging environment.",
    ...
}
```

The `PluginPermissionRule` in the policy engine maps `permission_level` to mode-dependent
behavior:

| `permission_level` | Read-only | Ask | Auto |
|---|---|---|---|
| `safe` | Auto-allow | Auto-allow | Auto-allow |
| `dangerous` | Deny | Prompt | Prompt (auto doesn't skip approval for dangerous plugins) |
| `restricted` | Deny | Deny | Deny |

`restricted` means the tool should never run in this environment regardless of mode — useful for
plugins that are installed globally but should not be available to this particular agent instance.

The level is a declaration about the plugin's nature, not an override of the mode. The mode
still controls the envelope:

- In **read-only**, even a `safe` plugin that writes files would be caught by `ReadOnlyRule`
  before `PluginPermissionRule` runs (because rules are ordered, and `ReadOnlyRule` fires first
  for any write tool).
- In **auto**, a `dangerous` plugin still prompts — the mode does not auto-approve actions
  outside the core tool set.

## Where the mode appears in the loop

The mode is resolved at startup, not per-call. The `_policy` object is a module-level singleton
in `src/agent.py`:

```python
# src/agent.py (planned extension)
from policy import build_engine

_policy = build_engine()   # reads AGENT_PERMISSION_MODE once

async def _execute_one_tool(tool_call: dict) -> ToolResult:
    name = tool_call["name"]
    args = tool_call["input"]

    decision = _policy.check(name, args)

    if decision.outcome == "deny":
        return ToolResult(tool_call["id"], name, f"Error: {decision.reason}", is_error=True)

    if decision.outcome == "ask":
        approved = await _prompt_user(name, args)
        if not approved:
            return ToolResult(tool_call["id"], name, "Tool call not approved.", is_error=True)

    # outcome == "allow" — dispatch
    fn = TOOL_REGISTRY.get(name)
    ...
```

The mode switch (`AGENT_PERMISSION_MODE=read-only python main.py "..."`) requires no code
changes. The same agent binary runs in all three postures.

## Interaction with parallel tool calls

The agent executes tool calls in parallel via `asyncio.gather`. In `ask` mode, multiple
dangerous tool calls in the same turn would each trigger an `input()` prompt concurrently —
their output would interleave on the terminal.

Serialize prompts with an `asyncio.Lock` (allow-decisions still run concurrently):

```python
_prompt_lock = asyncio.Lock()

async def _prompt_user(name: str, args: dict) -> bool:
    async with _prompt_lock:
        print(f"\n[APPROVAL NEEDED] {name}: {args}")
        return input("Allow? [y/N] ").strip().lower() == "y"
```

Read-only auto-allows bypass the lock entirely, so exploration tool calls stay concurrent.

## Configuring the mode

Set `AGENT_PERMISSION_MODE` in the environment before running:

```bash
# Read-only exploration
AGENT_PERMISSION_MODE=read-only python main.py "Summarise the project structure"

# Interactive development (default)
python main.py "Fix the failing test in tests/test_utils.py"

# Automated CI
AGENT_PERMISSION_MODE=auto AGENT_BASH_ALLOWLIST="pytest,git,python" \
    python main.py "Run the full test suite and report failures"
```

The `AGENT_BASH_ALLOWLIST` environment variable (documented in
[Command Allowlist](../operations/command-allowlist.md)) narrows the set of permitted commands
within auto mode. See [Settings Reference](../operations/settings.md) for the full list of
environment variables.

## Trade-offs

| | Benefit | Cost |
|---|---|---|
| **Single env var** | Easy to change posture per invocation, scriptable in CI | A misconfigured mode (e.g. `read-only` in a task that requires writes) causes the agent to fail fast with denied tool calls — which is correct but requires the caller to configure it properly |
| **Mode as engine input, not engine rule** | Keeps rule logic separate from posture logic; rules stay testable | The mode is implicit context; a rule that inspects args has no direct access to it (pass it in at construction time, as `PluginPermissionRule` does) |
| **ask mode + stdin prompt** | Human stays in the loop | Blocks on `input()` — incompatible with headless / non-interactive environments; use `read-only` or `auto` in those contexts |
| **auto mode default-deny** | CI safety — unknown commands fail closed | The allowlist must be maintained; a command not on it requires a config change, not just a re-run |

## Related

- [Permissions & Gating](../operations/permissions.md) — the `beforeToolCall` hook and simpler per-tool gates this builds on
- [Command Allowlist](../operations/command-allowlist.md) — the allowlist that auto mode enforces for `bash`
- [Settings Reference](../operations/settings.md) — all environment variables, including `AGENT_PERMISSION_MODE` and `AGENT_BASH_ALLOWLIST`
- [Policy Engine](./policy-engine.md) — the rule-composing layer the mode switch controls
- [Plugin Architecture](./plugin-architecture.md) — where `permission_level` is declared on plugin tools
