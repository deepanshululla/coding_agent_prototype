"""CLI parsing + validation for the --dir flag (the agent's working folder).

--dir PATH points the agent (TUI or stdout) at a folder: main applies it with
os.chdir before building the prompt, so every tool — read_file, bash, grep,
list_dir — resolves paths there. Mirrors --model: one token follows the flag and
is removed from the task tokens.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import main  # noqa: E402


def test_extract_dir_absent_returns_none():
    task, directory = main._extract_dir(["summarize", "this", "repo"])
    assert directory is None
    assert task == ["summarize", "this", "repo"]


def test_extract_dir_extracts_path_and_strips_it():
    task, directory = main._extract_dir(["--dir", "/tmp/project", "fix the bug"])
    assert directory == "/tmp/project"
    assert task == ["fix the bug"]


def test_extract_dir_preserves_surrounding_args():
    task, directory = main._extract_dir(["before", "--dir", "/work", "after", "task"])
    assert directory == "/work"
    assert task == ["before", "after", "task"]


def test_resolve_dir_returns_absolute_for_existing(tmp_path):
    resolved = main._resolve_dir(str(tmp_path))
    assert resolved == str(tmp_path.resolve())


def test_resolve_dir_rejects_missing_path(tmp_path):
    missing = tmp_path / "does_not_exist"
    with pytest.raises(SystemExit):
        main._resolve_dir(str(missing))


def test_resolve_dir_rejects_a_file(tmp_path):
    f = tmp_path / "afile.txt"
    f.write_text("x")
    with pytest.raises(SystemExit):
        main._resolve_dir(str(f))
