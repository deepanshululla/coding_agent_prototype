"""Tests for src/config.py — the centralised AGENT_* reader.

config.py reads env vars at module import time, so each test reloads the module
under a patched environment with importlib.reload.
"""

import importlib

import pytest

import config as config_module


def _reload(monkeypatch, **env):
    """Reload config with the given AGENT_* env vars set (others cleared)."""
    for key in list(env):
        monkeypatch.setenv(key, env[key])
    return importlib.reload(config_module)


def test_int_reads_env_var(monkeypatch):
    cfg = _reload(monkeypatch, AGENT_MAX_ITERATIONS="7")
    assert cfg.MAX_ITERATIONS == 7


def test_int_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("AGENT_MAX_ITERATIONS", raising=False)
    cfg = importlib.reload(config_module)
    assert cfg.MAX_ITERATIONS == 30


def test_int_raises_systemexit_on_non_integer(monkeypatch):
    monkeypatch.setenv("AGENT_BASH_TIMEOUT", "lots")
    with pytest.raises(SystemExit):
        importlib.reload(config_module)


def test_csv_returns_default_list_when_unset(monkeypatch):
    monkeypatch.delenv("AGENT_BASH_ALLOWLIST", raising=False)
    cfg = importlib.reload(config_module)
    assert cfg.BASH_ALLOWLIST == []


def test_csv_splits_and_strips(monkeypatch):
    cfg = _reload(monkeypatch, AGENT_BASH_ALLOWLIST="ls, cat , git")
    assert cfg.BASH_ALLOWLIST == ["ls", "cat", "git"]


def test_model_reads_env_var(monkeypatch):
    cfg = _reload(monkeypatch, AGENT_MODEL="gpt-4o")
    assert cfg.MODEL == "gpt-4o"


def test_permission_mode_default(monkeypatch):
    monkeypatch.delenv("AGENT_PERMISSION_MODE", raising=False)
    cfg = importlib.reload(config_module)
    assert cfg.PERMISSION_MODE == "auto"


def test_bash_output_limit_reads_env(monkeypatch):
    cfg = _reload(monkeypatch, AGENT_BASH_OUTPUT_LIMIT="500")
    assert cfg.BASH_OUTPUT_LIMIT == 500


@pytest.fixture(autouse=True)
def _restore_config():
    """Reload config with the real environment after each test."""
    yield
    importlib.reload(config_module)
