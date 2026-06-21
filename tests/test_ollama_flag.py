"""Test the --ollama flag for convenient Ollama model selection."""

import sys
from pathlib import Path

# Add parent directory to path to import main
sys.path.insert(0, str(Path(__file__).parent.parent))

import main  # noqa: E402


def test_ollama_flag_default_model():
    """--ollama with no argument should use default ollama/llama3.2"""
    args = ["--ollama", "test task"]
    remaining, model = main._extract_ollama(args)

    assert model == "ollama/llama3.2"
    assert remaining == ["test task"]


def test_ollama_flag_with_model_name():
    """--ollama with model name should use ollama/<model>"""
    args = ["--ollama", "llama3.1", "test task"]
    remaining, model = main._extract_ollama(args)

    assert model == "ollama/llama3.1"
    assert remaining == ["test task"]


def test_ollama_flag_with_slash_prefix():
    """--ollama with ollama/ prefix should not duplicate it"""
    args = ["--ollama", "ollama/llama3.1", "test task"]
    remaining, model = main._extract_ollama(args)

    assert model == "ollama/llama3.1"
    assert remaining == ["test task"]


def test_ollama_flag_without_flag():
    """When --ollama is absent, returns None (no override)"""
    args = ["test task"]
    remaining, model = main._extract_ollama(args)

    assert model is None
    assert remaining == ["test task"]


def test_ollama_flag_at_end():
    """--ollama at the end without a model uses default"""
    args = ["test task", "--ollama"]
    remaining, model = main._extract_ollama(args)

    assert model == "ollama/llama3.2"
    assert remaining == ["test task"]
