"""Default-deny command allowlist for the bash tool.

check_command(command) → Verdict
  .allowed = True  → the command may run
  .allowed = False → the command is refused; .reason explains why

Shell metacharacters are rejected before program-name checking,
because `shell=True` means a command is a shell program, not a
single invocation. `git status; rm -rf /` starts with an allowlisted
program but does something else entirely.

The cost of rejecting metacharacters is that compound commands like
`cd build && make` are also blocked; the model must issue one simple
command per `bash` call.
"""

import os
import shlex
from dataclasses import dataclass

# Characters that allow a command to chain, substitute, or redirect.
# If any of these appear, the command defeats per-program checking.
SHELL_METACHARACTERS = (";", "&", "|", "$", "`", ">", "<", "(", ")", "\n", "\\")

# Default allowed programs. Read-only and project-safe.
# Override with AGENT_BASH_ALLOWLIST="ls,cat,git,pytest" (csv).
DEFAULT_ALLOWED_PROGRAMS: set[str] = {
    "ls",
    "cat",
    "head",
    "tail",
    "wc",
    "echo",
    "git",
    "python",
    "python3",
    "pytest",
    "grep",
    "rg",
    "find",
}

# Per-program subcommand allowlists (restrict dangerous subcommands).
PROGRAM_ARG_RULES: dict[str, set[str]] = {
    "git": {"status", "log", "diff", "show", "branch", "stash"},
}


def _load_allowlist() -> set[str]:
    raw = os.environ.get("AGENT_BASH_ALLOWLIST")
    if raw:
        return {p.strip() for p in raw.split(",") if p.strip()}
    return DEFAULT_ALLOWED_PROGRAMS


@dataclass
class Verdict:
    allowed: bool
    reason: str = ""


def check_command(command: str) -> Verdict:
    """Return a Verdict for the given shell command string."""
    command = command.strip()
    if not command:
        return Verdict(False, "empty command")

    # 1. Reject shell metacharacters — they defeat per-program checks.
    found = [ch for ch in SHELL_METACHARACTERS if ch in command]
    if found:
        return Verdict(
            False,
            f"command uses shell features {found} which are not permitted; "
            "run a single simple command instead",
        )

    # 2. Parse into argv; shlex mirrors shell tokenisation.
    try:
        argv = shlex.split(command)
    except ValueError as e:
        return Verdict(False, f"could not parse command: {e}")
    if not argv:
        return Verdict(False, "no program in command")

    program = argv[0]
    allowed = _load_allowlist()

    # 3. Program must be on the allowlist.
    if program not in allowed:
        return Verdict(
            False,
            f"'{program}' is not an allowed command. Allowed: {', '.join(sorted(allowed))}. "
            "Ask the user to add it to AGENT_BASH_ALLOWLIST, or use an allowed command.",
        )

    # 4. Per-program subcommand rules, if any.
    rules = PROGRAM_ARG_RULES.get(program)
    if rules is not None:
        sub = argv[1] if len(argv) > 1 else ""
        if sub not in rules:
            return Verdict(
                False,
                f"'{program} {sub}' is not allowed; permitted {program} subcommands: "
                f"{', '.join(sorted(rules))}",
            )

    return Verdict(True)
