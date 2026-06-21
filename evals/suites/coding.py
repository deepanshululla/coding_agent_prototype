"""A coding suite: small standalone functions graded by hidden tests.

The fast, local, no-network coding benchmark — the coding analogue of toolcall.
Each task ships a stub ``solution.py`` (signature, no real body) and a hidden
``test_solution.py``; the agent implements the function and is graded by running
those tests with :func:`pytest_grader`. HumanEval-flavoured but self-contained,
so a model comparison runs in minutes. (Breadth lives in the external ``polyglot``
suite; whole-repo work in ``swebench``.)

Because each task runs in its own temp workdir, every task safely reuses the
``solution.py`` / ``test_solution.py`` filenames. Set ``AGENT_CODE_MODEL`` to run
the suite in dual-model mode and measure the write_code delegation (ADR-0015).
"""

from evals.graders import pytest_grader
from evals.harness import Task

_PROMPT = (
    "Implement the {fn} function in solution.py so that the tests pass. "
    "Edit solution.py only — do not modify any test file."
)


def _task(task_id: str, fn: str, stub: str, test: str) -> Task:
    return Task(
        id=task_id,
        prompt=_PROMPT.format(fn=fn),
        files={"solution.py": stub, "test_solution.py": test},
        grader=pytest_grader("test_solution.py"),
    )


CODING_SUITE: list[Task] = [
    _task(
        "is-palindrome",
        "is_palindrome(s)",
        "def is_palindrome(s):\n"
        '    """True if s is a palindrome, ignoring case and non-alphanumerics."""\n'
        "    pass\n",
        "from solution import is_palindrome\n\n"
        "def test_palindrome():\n"
        "    assert is_palindrome('A man, a plan, a canal: Panama')\n"
        "    assert is_palindrome('')\n"
        "    assert not is_palindrome('hello')\n",
    ),
    _task(
        "fizzbuzz",
        "fizzbuzz(n)",
        "def fizzbuzz(n):\n"
        "    \"\"\"Return a list for 1..n: 'Fizz' for /3, 'Buzz' for /5, 'FizzBuzz' for\n"
        '    both, else the number as a string."""\n'
        "    pass\n",
        "from solution import fizzbuzz\n\n"
        "def test_fizzbuzz():\n"
        "    assert fizzbuzz(5) == ['1', '2', 'Fizz', '4', 'Buzz']\n"
        "    assert fizzbuzz(15)[-1] == 'FizzBuzz'\n"
        "    assert fizzbuzz(3)[2] == 'Fizz'\n",
    ),
    _task(
        "fib",
        "fib(n)",
        "def fib(n):\n"
        '    """The nth Fibonacci number, 0-indexed: fib(0)=0, fib(1)=1."""\n'
        "    pass\n",
        "from solution import fib\n\n"
        "def test_fib():\n"
        "    assert fib(0) == 0\n"
        "    assert fib(1) == 1\n"
        "    assert fib(10) == 55\n",
    ),
    _task(
        "two-sum",
        "two_sum(nums, target)",
        "def two_sum(nums, target):\n"
        '    """Return indices [i, j] of the two numbers that add up to target."""\n'
        "    pass\n",
        "from solution import two_sum\n\n"
        "def test_two_sum():\n"
        "    assert sorted(two_sum([2, 7, 11, 15], 9)) == [0, 1]\n"
        "    assert sorted(two_sum([3, 2, 4], 6)) == [1, 2]\n",
    ),
    _task(
        "roman-to-int",
        "roman_to_int(s)",
        'def roman_to_int(s):\n    """Convert a Roman numeral string to an integer."""\n    pass\n',
        "from solution import roman_to_int\n\n"
        "def test_roman():\n"
        "    assert roman_to_int('III') == 3\n"
        "    assert roman_to_int('IV') == 4\n"
        "    assert roman_to_int('MCMXCIV') == 1994\n",
    ),
    _task(
        "anagram",
        "is_anagram(a, b)",
        "def is_anagram(a, b):\n"
        '    """True if a and b are anagrams (case-insensitive, ignoring spaces)."""\n'
        "    pass\n",
        "from solution import is_anagram\n\n"
        "def test_anagram():\n"
        "    assert is_anagram('listen', 'silent')\n"
        "    assert is_anagram('Dormitory', 'dirty room')\n"
        "    assert not is_anagram('hello', 'world')\n",
    ),
    _task(
        "gcd",
        "gcd(a, b)",
        'def gcd(a, b):\n    """Greatest common divisor of two positive integers."""\n    pass\n',
        "from solution import gcd\n\n"
        "def test_gcd():\n"
        "    assert gcd(12, 18) == 6\n"
        "    assert gcd(17, 5) == 1\n"
        "    assert gcd(100, 10) == 10\n",
    ),
    _task(
        "flatten",
        "flatten(xs)",
        "def flatten(xs):\n"
        '    """Flatten an arbitrarily nested list of integers into a flat list."""\n'
        "    pass\n",
        "from solution import flatten\n\n"
        "def test_flatten():\n"
        "    assert flatten([1, [2, [3, 4], 5]]) == [1, 2, 3, 4, 5]\n"
        "    assert flatten([]) == []\n"
        "    assert flatten([[1], [2], [3]]) == [1, 2, 3]\n",
    ),
]
