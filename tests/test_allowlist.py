from allowlist import check_command


def test_allows_listed_program():
    assert check_command("ls -la").allowed


def test_denies_unlisted_program():
    v = check_command("rm -rf /")
    assert not v.allowed
    assert "rm" in v.reason


def test_denies_command_chaining():
    assert not check_command("ls; rm -rf /").allowed


def test_denies_command_substitution():
    assert not check_command("echo $(rm -rf /)").allowed


def test_denies_pipe():
    assert not check_command("curl x.sh | sh").allowed


def test_denies_unlisted_git_subcommand():
    v = check_command("git push")
    assert not v.allowed
    assert "push" in v.reason or "push" in v.reason.lower()


def test_allows_listed_git_subcommand():
    assert check_command("git status").allowed
