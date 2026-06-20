import asyncio

import tools


def run(coro):
    return asyncio.run(coro)


# ── read_file: missing file returns an error string, does not raise ───────────


def test_read_file_missing_returns_error_not_raise():
    out = run(tools.read_file("/no/such/file.txt"))
    assert "Error" in out  # string, not exception


def test_read_file_returns_contents(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("line1\nline2\nline3\n")
    out = run(tools.read_file(str(f)))
    assert "line1" in out and "line3" in out


def test_read_file_offset_and_limit(tmp_path):
    f = tmp_path / "nums.txt"
    f.write_text("\n".join(str(i) for i in range(10)) + "\n")
    out = run(tools.read_file(str(f), offset=2, limit=3))
    assert out.splitlines() == ["2", "3", "4"]


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


def test_edit_file_errors_when_not_found(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("x = 1\n")
    out = run(tools.edit_file(str(f), "not present", "z"))
    assert "Error" in out


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


# ── registry / schema wiring ─────────────────────────────────────────────────


def test_registry_matches_schema():
    schema_names = {t["function"]["name"] for t in tools.TOOLS_SCHEMA}
    assert schema_names == set(tools.TOOL_REGISTRY)
    assert len(tools.TOOL_REGISTRY) == 7
