"""Tests for the Aider polyglot suite loader.

The loader turns a checked-out polyglot-benchmark repo into `Task`s. These tests
build a tiny fake repo in tmp_path so they exercise the real directory-walking
and Task-construction logic with no network and no clone.

Real exercise layout (python):
    <lang>/exercises/practice/<slug>/
        .docs/instructions.md          # problem statement
        .docs/instructions.append.md   # optional extra
        <module>.py                    # stub the agent fills in
        <module>_test.py               # hidden tests
        .meta/example.py               # reference solution — must NOT be exposed
"""

from pathlib import Path

from evals.suites.polyglot import load_polyglot


def _make_exercise(root: Path, slug: str, module: str, *, append: bool = False) -> None:
    ex = root / "python" / "exercises" / "practice" / slug
    docs = ex / ".docs"
    meta = ex / ".meta"
    docs.mkdir(parents=True)
    meta.mkdir(parents=True)
    (docs / "instructions.md").write_text(f"# Instructions\n\nImplement {slug}.\n")
    if append:
        (docs / "instructions.append.md").write_text("Extra note: edge cases matter.\n")
    (ex / f"{module}.py").write_text("def solve():\n    pass\n")
    (ex / f"{module}_test.py").write_text(
        f"from {module} import solve\n\ndef test_solve():\n    assert solve() == 42\n"
    )
    (meta / "example.py").write_text("def solve():\n    return 42  # REFERENCE\n")


def test_loads_one_task_per_exercise(tmp_path):
    _make_exercise(tmp_path, "anagram", "anagram")
    _make_exercise(tmp_path, "two-fer", "two_fer")
    tasks = load_polyglot(tmp_path)
    assert len(tasks) == 2
    assert {t.id for t in tasks} == {"python/anagram", "python/two-fer"}


def test_prompt_includes_instructions(tmp_path):
    _make_exercise(tmp_path, "anagram", "anagram")
    task = load_polyglot(tmp_path)[0]
    assert "Implement anagram" in task.prompt


def test_prompt_includes_appended_instructions(tmp_path):
    _make_exercise(tmp_path, "anagram", "anagram", append=True)
    task = load_polyglot(tmp_path)[0]
    assert "edge cases matter" in task.prompt


def test_prompt_warns_against_editing_tests(tmp_path):
    _make_exercise(tmp_path, "anagram", "anagram")
    task = load_polyglot(tmp_path)[0]
    assert "test" in task.prompt.lower()
    assert "anagram_test.py" in task.prompt


def test_seed_files_include_stub_and_test_but_not_reference(tmp_path):
    _make_exercise(tmp_path, "anagram", "anagram")
    task = load_polyglot(tmp_path)[0]
    assert "anagram.py" in task.files
    assert "anagram_test.py" in task.files
    # The reference solution must never reach the agent.
    assert not any("example.py" in name or "REFERENCE" in body for name, body in task.files.items())


def test_grader_passes_only_when_tests_pass(tmp_path):
    _make_exercise(tmp_path, "anagram", "anagram")
    task = load_polyglot(tmp_path)[0]
    work = tmp_path / "work"
    work.mkdir()
    for name, body in task.files.items():
        (work / name).write_text(body)
    # Stub returns None -> tests fail.
    assert task.grader(work).passed is False
    # Drop in the working solution -> tests pass.
    (work / "anagram.py").write_text("def solve():\n    return 42\n")
    assert task.grader(work).passed is True


def test_tasks_are_sorted_by_slug(tmp_path):
    _make_exercise(tmp_path, "zebra", "zebra")
    _make_exercise(tmp_path, "apple", "apple")
    ids = [t.id for t in load_polyglot(tmp_path)]
    assert ids == sorted(ids)
