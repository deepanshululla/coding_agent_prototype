"""Unit tests for the seven tools.

Tools are async, so each test drives them through ``asyncio.run`` — this avoids a
pytest-asyncio dependency. The contract under test throughout: tools return strings and
never raise, even on bad input.
"""

import asyncio

import tools


def run(coro):
    return asyncio.run(coro)


# ── read_file ────────────────────────────────────────────────────────────────


def test_read_file_returns_contents(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("line1\nline2\nline3\n")
    out = run(tools.read_file(str(f)))
    assert "line1" in out and "line3" in out


def test_read_file_offset_and_limit(tmp_path):
    f = tmp_path / "nums.txt"
    f.write_text("\n".join(str(i) for i in range(10)) + "\n")
    out = run(tools.read_file(str(f), offset=2, limit=3))
    lines = out.splitlines()
    assert lines == ["2", "3", "4"]


def test_read_file_missing_returns_error_not_raise():
    out = run(tools.read_file("/no/such/file.txt"))
    assert "Error" in out or "error" in out


# ── write_file ───────────────────────────────────────────────────────────────


def test_write_file_creates_parent_dirs(tmp_path):
    target = tmp_path / "a" / "b" / "c.txt"
    out = run(tools.write_file(str(target), "payload"))
    assert target.read_text() == "payload"
    assert "c.txt" in out


# ── edit_file ────────────────────────────────────────────────────────────────


def test_edit_file_replaces_unique_string(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("x = 1\ny = 2\n")
    run(tools.edit_file(str(f), "y = 2", "y = 3"))
    assert f.read_text() == "x = 1\ny = 3\n"


def test_edit_file_errors_when_missing(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("x = 1\n")
    out = run(tools.edit_file(str(f), "not present", "z"))
    assert "Error" in out or "not found" in out.lower()


def test_edit_file_errors_when_not_unique(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("a\na\n")
    out = run(tools.edit_file(str(f), "a", "b"))
    assert "unique" in out.lower() or "Error" in out


# ── bash ─────────────────────────────────────────────────────────────────────


def test_bash_runs_command():
    out = run(tools.bash("echo hello-from-bash"))
    assert "hello-from-bash" in out


def test_bash_reports_exit_code():
    out = run(tools.bash("exit 3"))
    assert "3" in out


# ── grep ─────────────────────────────────────────────────────────────────────


def test_grep_finds_pattern(tmp_path):
    (tmp_path / "f.txt").write_text("needle here\nhaystack\n")
    out = run(tools.grep("needle", str(tmp_path)))
    assert "needle" in out


# ── find_files ───────────────────────────────────────────────────────────────


def test_find_files_by_name(tmp_path):
    (tmp_path / "keep.py").write_text("")
    (tmp_path / "skip.txt").write_text("")
    out = run(tools.find_files("*.py", str(tmp_path)))
    assert "keep.py" in out and "skip.txt" not in out


# ── list_dir ─────────────────────────────────────────────────────────────────


def test_list_dir_marks_directories(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "file.txt").write_text("hi")
    out = run(tools.list_dir(str(tmp_path)))
    assert "sub/" in out
    assert "file.txt" in out


# ── registry / schema wiring ─────────────────────────────────────────────────


def test_registry_matches_schema():
    schema_names = {t["function"]["name"] for t in tools.TOOLS_SCHEMA}
    assert schema_names == set(tools.TOOL_REGISTRY)
    assert len(tools.TOOL_REGISTRY) == 7
