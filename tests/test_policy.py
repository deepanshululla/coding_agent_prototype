import os

import pytest

from policy import (
    CommandAllowlistRule,
    PathRestrictionRule,
    PolicyEngine,
    ReadOnlyRule,
    ReadToolRule,
)

# ── ReadToolRule ─────────────────────────────────────────────────────────────


def test_read_tool_rule_allows_read_tools():
    rule = ReadToolRule()
    for name in ("read_file", "grep", "find_files", "list_dir"):
        d = rule.evaluate(name, {"path": "x"})
        assert d is not None and d.outcome == "allow"


def test_read_tool_rule_passes_write_tools():
    assert ReadToolRule().evaluate("write_file", {"path": "x"}) is None
    assert ReadToolRule().evaluate("bash", {"command": "ls"}) is None


# ── ReadOnlyRule ─────────────────────────────────────────────────────────────


def test_readonly_denies_write_file():
    d = ReadOnlyRule().evaluate("write_file", {"path": "x.py", "content": "y"})
    assert d is not None
    assert d.outcome == "deny"
    assert "read-only mode is active" in d.reason


def test_readonly_denies_bash_and_edit():
    rule = ReadOnlyRule()
    assert rule.evaluate("bash", {"command": "ls"}).outcome == "deny"
    assert rule.evaluate("edit_file", {"path": "x"}).outcome == "deny"


def test_readonly_passes_read_tools():
    assert ReadOnlyRule().evaluate("read_file", {"path": "x.py"}) is None


# ── CommandAllowlistRule ─────────────────────────────────────────────────────


def test_allowlist_rule_ignores_non_bash():
    assert CommandAllowlistRule().evaluate("write_file", {"path": "x"}) is None


def test_allowlist_rule_allows_listed_command():
    d = CommandAllowlistRule().evaluate("bash", {"command": "ls -la"})
    assert d is not None
    assert d.outcome == "allow"


def test_allowlist_rule_denies_unlisted_command():
    d = CommandAllowlistRule().evaluate("bash", {"command": "rm -rf /"})
    assert d is not None
    assert d.outcome == "deny"
    assert "rm" in d.reason


# ── PathRestrictionRule ──────────────────────────────────────────────────────


def test_path_rule_ignores_non_write_tools():
    rule = PathRestrictionRule(allowed_root=os.getcwd())
    assert rule.evaluate("bash", {"command": "ls"}) is None


def test_path_rule_allows_in_root(tmp_path):
    rule = PathRestrictionRule(allowed_root=str(tmp_path))
    inside = str(tmp_path / "sub" / "file.py")
    assert rule.evaluate("write_file", {"path": inside}) is None


def test_path_rule_denies_outside_root(tmp_path):
    rule = PathRestrictionRule(allowed_root=str(tmp_path / "project"))
    outside = str(tmp_path / "elsewhere" / "file.py")
    d = rule.evaluate("write_file", {"path": outside})
    assert d is not None
    assert d.outcome == "deny"
    assert "outside allowed root" in d.reason


# ── PolicyEngine.check (ordering + default) ──────────────────────────────────


def test_engine_first_non_none_rule_wins():
    engine = PolicyEngine(rules=[ReadOnlyRule()], default="allow")
    d = engine.check("write_file", {"path": "x"})
    assert d.outcome == "deny"


def test_engine_falls_through_to_default():
    engine = PolicyEngine(rules=[ReadOnlyRule()], default="ask")
    d = engine.check("read_file", {"path": "x"})
    assert d.outcome == "ask"
    assert "default applied" in d.reason


# ── PolicyEngine.from_env (each mode) ────────────────────────────────────────


def test_from_env_read_only(monkeypatch):
    monkeypatch.setenv("AGENT_PERMISSION_MODE", "read-only")
    engine = PolicyEngine.from_env()
    assert engine.default == "deny"
    assert engine.check("write_file", {"path": "x"}).outcome == "deny"
    # read tools run freely even in read-only mode
    assert engine.check("read_file", {"path": "x"}).outcome == "allow"


def test_from_env_auto(monkeypatch):
    monkeypatch.setenv("AGENT_PERMISSION_MODE", "auto")
    engine = PolicyEngine.from_env()
    assert engine.default == "deny"
    # allowlisted bash runs
    assert engine.check("bash", {"command": "ls"}).outcome == "allow"
    # write inside cwd falls through to default deny (auto never asks)
    assert engine.check("write_file", {"path": "x.py"}).outcome == "deny"


def test_from_env_ask_default(monkeypatch):
    monkeypatch.delenv("AGENT_PERMISSION_MODE", raising=False)
    engine = PolicyEngine.from_env()
    assert engine.default == "ask"
    # write inside cwd hits no rule → default ask
    assert engine.check("write_file", {"path": "x.py"}).outcome == "ask"
    # allowlisted bash still runs without prompting
    assert engine.check("bash", {"command": "ls"}).outcome == "allow"


def test_from_env_ask_denies_out_of_root_write(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_PERMISSION_MODE", "ask")
    engine = PolicyEngine.from_env()
    outside = str(tmp_path / "elsewhere.py")
    # tmp_path is outside cwd → PathRestrictionRule denies without prompting
    assert engine.check("write_file", {"path": outside}).outcome == "deny"


# ── BDD scenario: permission modes gate write/execute tools ──────────────────
# Mirrors the Gherkin in the plan: read-only denies write_file; ask mode with
# the user typing "n" denies write_file. The write_file function is never
# called in either case.


@pytest.mark.asyncio
async def test_bdd_read_only_denies_write_file(monkeypatch):
    import agent
    from policy import PolicyEngine as PE

    called = False

    async def fake_write(**kwargs):
        nonlocal called
        called = True
        return "wrote"

    monkeypatch.setitem(agent.TOOL_REGISTRY, "write_file", fake_write)
    monkeypatch.setattr(agent, "_policy", PE(rules=[ReadOnlyRule()], default="deny"))

    result = await agent._execute_one_tool(
        {"id": "t1", "index": 0, "name": "write_file", "input": {"path": "x.py", "content": "y"}}
    )

    assert result.is_error is True
    assert "read-only mode is active" in result.content
    assert called is False


@pytest.mark.asyncio
async def test_bdd_ask_mode_user_denies_write_file(monkeypatch):
    import agent
    from policy import CommandAllowlistRule as CAR
    from policy import PathRestrictionRule as PRR
    from policy import PolicyEngine as PE

    called = False

    async def fake_write(**kwargs):
        nonlocal called
        called = True
        return "wrote"

    monkeypatch.setitem(agent.TOOL_REGISTRY, "write_file", fake_write)
    # ask-mode engine: write inside cwd hits no rule → default ask
    monkeypatch.setattr(agent, "_policy", PE(rules=[CAR(), PRR()], default="ask"))
    # user types "n" at the prompt
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")

    result = await agent._execute_one_tool(
        {"id": "t2", "index": 0, "name": "write_file", "input": {"path": "x.py", "content": "y"}}
    )

    assert result.is_error is True
    assert "not approved" in result.content
    assert called is False


@pytest.mark.asyncio
async def test_bdd_ask_mode_user_approves_write_file(monkeypatch):
    import agent
    from policy import CommandAllowlistRule as CAR
    from policy import PathRestrictionRule as PRR
    from policy import PolicyEngine as PE

    called = False

    async def fake_write(**kwargs):
        nonlocal called
        called = True
        return "wrote ok"

    monkeypatch.setitem(agent.TOOL_REGISTRY, "write_file", fake_write)
    monkeypatch.setattr(agent, "_policy", PE(rules=[CAR(), PRR()], default="ask"))
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    result = await agent._execute_one_tool(
        {"id": "t3", "index": 0, "name": "write_file", "input": {"path": "x.py", "content": "y"}}
    )

    assert result.is_error is False
    assert called is True
