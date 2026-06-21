"""Test that the --model flag is correctly parsed and passed through."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import main  # noqa: E402


def test_extract_model_with_flag():
    """--model <name> extracts the model and removes it from args."""
    args = ["--model", "ollama/llama3.2", "test task"]
    remaining, model = main._extract_model(args)

    assert model == "ollama/llama3.2"
    assert remaining == ["test task"]


def test_extract_model_without_flag():
    """When --model is absent, returns None (falls back to AGENT_MODEL)."""
    args = ["test task"]
    remaining, model = main._extract_model(args)

    assert model is None
    assert remaining == ["test task"]


def test_extract_model_flag_at_end():
    """--model at the end of args without a value returns None."""
    args = ["test task", "--model"]
    remaining, model = main._extract_model(args)

    assert model is None
    assert remaining == ["test task"]


def test_extract_model_with_other_flags():
    """--model works alongside other flags like --skills."""
    args = ["--skills", "explain", "--model", "gpt-4o", "explain the code"]
    remaining, model = main._extract_model(args)

    assert model == "gpt-4o"
    assert remaining == ["--skills", "explain", "explain the code"]
