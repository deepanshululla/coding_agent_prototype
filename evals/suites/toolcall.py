"""A tool-calling suite: tasks that can ONLY be solved by driving tools.

Where the smoke suite measures whether the agent gets the right *answer*, this
suite is built to stress the *tool-calling* itself — each task is shaped so a
model that can't reliably pick the right tool and pass it valid arguments will
fail, regardless of how good its prose is. Run across models (see
``evals.run --models`` / ``--ollama-all``) the pass-rate plus the per-run
ToolStats (calls / errors / hallucinated names) rank local Ollama models on
exactly the dimension that varies most between them.

Each task targets a tool path:

* ``read-secret``   — read_file: pull a value out of a seed file, write it back.
* ``grep-locate``   — grep/find/bash: find which file holds a token.
* ``edit-version``  — edit_file: change one constant in place, leave the rest.
* ``write-config``  — write_file: create a new file with exact contents.
* ``bash-count``    — bash: count lines via the shell.
* ``read-edit-chain`` — multi-step: read a number, double it, write the result.

All self-contained: no network, no external repo, graded by end-state.
"""

from evals.graders import command_grader, file_contains
from evals.harness import Task

TOOLCALL_SUITE: list[Task] = [
    Task(
        id="read-secret",
        prompt=(
            "The file vault.txt contains a line `SECRET=<value>`. Read it and "
            "write ONLY that value (the text after the `=`, nothing else) to "
            "answer.txt."
        ),
        files={"vault.txt": "noise\nSECRET=hunter2\nmore noise\n"},
        grader=command_grader('test "$(cat answer.txt)" = "hunter2"'),
    ),
    Task(
        id="grep-locate",
        prompt=(
            "Exactly one file in this directory contains the word NEEDLE. Find "
            "which file it is and write ONLY that file's name (e.g. b.txt) to "
            "found.txt."
        ),
        files={
            "a.txt": "the quick brown fox\n",
            "b.txt": "look a NEEDLE in here\n",
            "c.txt": "nothing to see\n",
        },
        grader=command_grader('test "$(cat found.txt)" = "b.txt"'),
    ),
    Task(
        id="edit-version",
        prompt=(
            'config.py defines VERSION = "1.0.0". Edit it in place so VERSION '
            'is "2.0.0". Do not change anything else in the file.'
        ),
        files={"config.py": 'NAME = "demo"\nVERSION = "1.0.0"\nDEBUG = False\n'},
        # Must bump the version AND preserve the surrounding lines.
        grader=command_grader(
            "grep -q 'VERSION = \"2.0.0\"' config.py "
            "&& grep -q 'NAME = \"demo\"' config.py "
            '&& grep -q "DEBUG = False" config.py'
        ),
    ),
    Task(
        id="write-config",
        prompt=(
            "Create a file settings.json with EXACTLY this content (one line):\n"
            '{"env": "prod", "retries": 3}'
        ),
        grader=file_contains("settings.json", '{"env": "prod", "retries": 3}'),
    ),
    Task(
        id="bash-count",
        prompt=(
            "Count how many lines are in log.txt and write ONLY that number "
            "(digits only) to count.txt."
        ),
        files={"log.txt": "l1\nl2\nl3\nl4\nl5\n"},
        grader=command_grader('test "$(cat count.txt)" = "5"'),
    ),
    Task(
        id="read-edit-chain",
        prompt=(
            "input.txt holds a single integer. Read it, double it, and write "
            "ONLY the doubled integer to output.txt."
        ),
        files={"input.txt": "21\n"},
        grader=command_grader('test "$(cat output.txt)" = "42"'),
    ),
    # ── more tasks, graduated difficulty (multi-file, multi-step, aggregation) ──
    Task(
        id="count-matching-files",
        prompt=(
            "Count how many files in this directory have a .log extension and "
            "write ONLY that number to result.txt."
        ),
        files={"a.log": "x", "b.log": "y", "c.txt": "z", "d.log": "w", "notes.md": "m"},
        grader=command_grader('test "$(cat result.txt)" = "3"'),
    ),
    Task(
        id="sum-numbers",
        prompt=(
            "nums.txt has one integer per line. Compute their sum and write ONLY "
            "the total to sum.txt."
        ),
        files={"nums.txt": "10\n20\n30\n40\n"},
        grader=command_grader('test "$(cat sum.txt)" = "100"'),
    ),
    Task(
        id="json-extract",
        prompt=(
            "config.json contains a JSON object. Read it and write ONLY the value "
            'of the "port" key to port.txt.'
        ),
        files={"config.json": '{"host": "localhost", "port": 8080, "debug": true}\n'},
        grader=command_grader('test "$(cat port.txt)" = "8080"'),
    ),
    Task(
        id="find-line-number",
        prompt=(
            "In poem.txt, find the 1-based line number of the line containing the "
            "word ZEBRA and write ONLY that number to line.txt."
        ),
        files={"poem.txt": "alpha\nbeta\nZEBRA here\ndelta\n"},
        grader=command_grader('test "$(cat line.txt)" = "3"'),
    ),
    Task(
        id="largest-number",
        prompt=("data.txt has one integer per line. Write ONLY the largest of them to max.txt."),
        files={"data.txt": "42\n7\n100\n3\n88\n"},
        grader=command_grader('test "$(cat max.txt)" = "100"'),
    ),
    Task(
        id="sort-lines",
        prompt=(
            "names.txt has one name per line. Write the names sorted alphabetically "
            "(one per line) to sorted.txt."
        ),
        files={"names.txt": "charlie\nalice\nbob\n"},
        grader=command_grader('printf "alice\\nbob\\ncharlie\\n" | diff - sorted.txt'),
    ),
    Task(
        id="csv-column",
        prompt=(
            "people.csv has a header row then data rows of name,age. Write the age "
            "of the person named 'Bob' to age.txt (just the number)."
        ),
        files={"people.csv": "name,age\nAlice,30\nBob,25\nCarol,40\n"},
        grader=command_grader('test "$(cat age.txt)" = "25"'),
    ),
    Task(
        id="two-file-merge",
        prompt=(
            "Read first.txt and second.txt and write their concatenation "
            "(first.txt's content, then second.txt's content) to merged.txt."
        ),
        files={"first.txt": "hello\n", "second.txt": "world\n"},
        grader=command_grader('printf "hello\\nworld\\n" | diff - merged.txt'),
    ),
    Task(
        id="conditional-write",
        prompt=(
            "If flag.txt contains the word ENABLED, write 'on' to state.txt; "
            "otherwise write 'off'. Read flag.txt first."
        ),
        files={"flag.txt": "status: ENABLED\n"},
        grader=command_grader('test "$(cat state.txt)" = "on"'),
    ),
    Task(
        id="multi-edit",
        prompt=(
            "settings.py has three lines: DEBUG = True, RETRIES = 1, TIMEOUT = 5. "
            "Change DEBUG to False and RETRIES to 3, leaving TIMEOUT unchanged."
        ),
        files={"settings.py": "DEBUG = True\nRETRIES = 1\nTIMEOUT = 5\n"},
        grader=command_grader(
            "grep -q 'DEBUG = False' settings.py && grep -q 'RETRIES = 3' settings.py "
            "&& grep -q 'TIMEOUT = 5' settings.py"
        ),
    ),
    Task(
        id="word-frequency",
        prompt=(
            "In text.txt, count how many times the word 'the' appears (case-insensitive, "
            "whole word) and write ONLY that count to count.txt."
        ),
        files={"text.txt": "The cat sat on the mat. THE end. another the.\n"},
        grader=command_grader('test "$(cat count.txt)" = "4"'),
    ),
    Task(
        id="nested-create",
        prompt=(
            "Create a file at src/lib/util.txt containing exactly the word 'ready' "
            "(creating directories as needed)."
        ),
        grader=command_grader('test "$(cat src/lib/util.txt)" = "ready"'),
    ),
    Task(
        id="find-in-subdir",
        prompt=(
            "Somewhere under the dir/ folder is a file containing the token SECRET42. "
            "Find it and write the token's value (the part after SECRET) to found.txt — "
            "so found.txt should contain '42'."
        ),
        files={
            "dir/a/x.txt": "nothing\n",
            "dir/b/y.txt": "here is SECRET42 hidden\n",
            "dir/c/z.txt": "decoy\n",
        },
        grader=command_grader('test "$(cat found.txt)" = "42"'),
    ),
    Task(
        id="dedupe-lines",
        prompt=(
            "items.txt has duplicate lines. Write the unique lines, preserving first-seen "
            "order, to unique.txt."
        ),
        files={"items.txt": "apple\nbanana\napple\ncherry\nbanana\n"},
        grader=command_grader('printf "apple\\nbanana\\ncherry\\n" | diff - unique.txt'),
    ),
]
