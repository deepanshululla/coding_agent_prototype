"""Tests for the SWE-bench Lite suite.

SWE-bench grading is necessarily a separate batch step (the official harness
builds per-instance Docker images). This suite's job is the *prediction* half:
clone each instance's repo at its base commit, let the agent edit it, and
capture the resulting diff in SWE-bench predictions format. These tests cover
the parsing, the clone setup, the diff-capturing grader, task construction, and
the predictions writer — using local git repos so nothing hits the network.
"""

import json
import subprocess
from pathlib import Path

from evals.harness import EvalResult
from evals.suites.swebench import (
    capture_patch_grader,
    clone_setup,
    github_url,
    load_swebench,
    parse_instances,
    write_predictions,
)


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _make_repo(path: Path) -> str:
    """Create a local git repo with two commits; return the FIRST commit's sha."""
    path.mkdir()
    _git("init", "-q", cwd=path)
    _git("config", "user.email", "t@t.com", cwd=path)
    _git("config", "user.name", "t", cwd=path)
    (path / "calc.py").write_text("def add(a, b):\n    return a - b  # bug\n")
    _git("add", "-A", cwd=path)
    _git("commit", "-qm", "first", cwd=path)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True
    ).stdout.strip()
    # A later commit so "clone then checkout base" is a meaningful operation.
    (path / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    _git("commit", "-aqm", "second", cwd=path)
    return sha


# ── parsing ──────────────────────────────────────────────────────────────────


def test_parse_instances_decodes_test_lists():
    rows = [
        {
            "instance_id": "x__y-1",
            "repo": "x/y",
            "base_commit": "abc",
            "problem_statement": "fix it",
            "test_patch": "",
            "FAIL_TO_PASS": '["test_a", "test_b"]',  # JSON-encoded in the dataset
            "PASS_TO_PASS": '["test_c"]',
        }
    ]
    [inst] = parse_instances(rows)
    assert inst.instance_id == "x__y-1"
    assert inst.repo == "x/y"
    assert inst.fail_to_pass == ["test_a", "test_b"]
    assert inst.pass_to_pass == ["test_c"]


def test_github_url_builds_clone_url():
    assert github_url("django/django") == "https://github.com/django/django.git"


# ── clone setup ──────────────────────────────────────────────────────────────


def test_clone_setup_checks_out_the_base_commit(tmp_path):
    origin = tmp_path / "origin"
    base_sha = _make_repo(origin)

    work = tmp_path / "work"
    work.mkdir()
    # Point the clone at the local repo instead of GitHub.
    clone_setup(str(origin), base_sha)(work)

    # The workdir should be the repo *at the base commit* (the buggy version).
    assert "a - b" in (work / "calc.py").read_text()
    assert (work / ".git").exists()


# ── diff-capturing grader ────────────────────────────────────────────────────


def test_capture_patch_grader_returns_the_diff_as_artifact(tmp_path):
    origin = tmp_path / "origin"
    base_sha = _make_repo(origin)
    work = tmp_path / "work"
    work.mkdir()
    clone_setup(str(origin), base_sha)(work)

    # Simulate the agent fixing the bug.
    (work / "calc.py").write_text("def add(a, b):\n    return a + b\n")

    result = capture_patch_grader()(work)
    assert result.passed is True  # a non-empty patch was produced
    assert result.artifact is not None
    assert "a + b" in result.artifact
    assert result.artifact.startswith("diff --git")


def test_capture_patch_grader_fails_when_no_changes(tmp_path):
    origin = tmp_path / "origin"
    base_sha = _make_repo(origin)
    work = tmp_path / "work"
    work.mkdir()
    clone_setup(str(origin), base_sha)(work)

    result = capture_patch_grader()(work)
    assert result.passed is False  # agent made no edit -> empty patch


# ── task construction ────────────────────────────────────────────────────────


def test_load_swebench_builds_one_task_per_instance():
    rows = [
        {
            "instance_id": "x__y-1",
            "repo": "x/y",
            "base_commit": "abc",
            "problem_statement": "Fix the off-by-one in add().",
            "test_patch": "",
            "FAIL_TO_PASS": "[]",
            "PASS_TO_PASS": "[]",
        }
    ]
    tasks = load_swebench(parse_instances(rows))
    assert len(tasks) == 1
    task = tasks[0]
    assert task.id == "x__y-1"
    assert "off-by-one" in task.prompt
    assert task.setup is not None  # clones the repo


# ── predictions writer ───────────────────────────────────────────────────────


def test_write_predictions_emits_swebench_format(tmp_path):
    results = [
        EvalResult("x__y-1", True, "1 file changed", 100, 1.0, artifact="THE DIFF"),
        EvalResult("x__y-2", False, "no patch", 50, 1.0, artifact=None),
    ]
    path = tmp_path / "preds.jsonl"
    write_predictions(path, results, model="claude")

    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[0] == {
        "instance_id": "x__y-1",
        "model_name_or_path": "claude",
        "model_patch": "THE DIFF",
    }
    # Missing artifact -> empty patch (so the harness records it as unresolved).
    assert records[1]["model_patch"] == ""
