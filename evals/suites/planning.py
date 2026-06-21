"""A planning suite: produce a valid ordered plan under dependency constraints.

Planning effectiveness is the model's ability to take a goal plus precedence
constraints and emit a correct ordered sequence of steps — respecting every
dependency, including all required steps, with no impossible ordering. It is the
agentic-reasoning axis that underlies good tool use: a model that can't order
"lint before build before test before deploy" won't drive a real task well.

Each task is graded by :func:`valid_ordering`, which accepts *any* valid
topological order (a DAG has many), so the benchmark rewards correct planning
rather than guessing one canonical answer. Tasks are answer-graded (no tools),
so they also run on tool-less models (gemma3) via the provider's no-tools path.

Every prompt ends with the same instruction so the gradeable plan is isolated
after a ``PLAN:`` marker, below any step-by-step reasoning.
"""

import random

from evals.graders import valid_ordering
from evals.harness import Task

_FORMAT = (
    " Think it through, then on the final line write 'PLAN:' followed by the "
    "steps in order, separated by ' -> ', using exactly the step labels given."
)


def _task(task_id: str, problem: str, required: list[str], before: list[tuple[str, str]]) -> Task:
    return Task(
        id=task_id,
        prompt=problem + _FORMAT,
        grader=valid_ordering(required, before),
    )


PLANNING_SUITE: list[Task] = [
    _task(
        "deploy-pipeline",
        "You are releasing software. Steps: lint, build, test, deploy, announce. "
        "Rules: you must lint before build, build before test, test before deploy, "
        "and deploy before announce. Give a valid order.",
        ["lint", "build", "test", "deploy", "announce"],
        [("lint", "build"), ("build", "test"), ("test", "deploy"), ("deploy", "announce")],
    ),
    _task(
        "get-dressed",
        "Getting dressed. Steps: underwear, pants, belt, shirt, jacket, socks, shoes. "
        "Rules: underwear before pants, pants before belt, shirt before jacket, "
        "socks before shoes, and pants before shoes. Give a valid order.",
        ["underwear", "pants", "belt", "shirt", "jacket", "socks", "shoes"],
        [
            ("underwear", "pants"),
            ("pants", "belt"),
            ("shirt", "jacket"),
            ("socks", "shoes"),
            ("pants", "shoes"),
        ],
    ),
    _task(
        "course-prereqs",
        "Plan which courses to take. Courses: intro, data, algorithms, ml, systems. "
        "Prerequisites: intro before data, data before algorithms, algorithms before ml, "
        "intro before systems. Give a valid order to take them one at a time.",
        ["intro", "data", "algorithms", "ml", "systems"],
        [("intro", "data"), ("data", "algorithms"), ("algorithms", "ml"), ("intro", "systems")],
    ),
    _task(
        "make-tea",
        "Make a cup of tea. Steps: boil, pour, steep, add-milk, drink. "
        "Rules: boil before pour, pour before steep, steep before add-milk, "
        "add-milk before drink. Give a valid order.",
        ["boil", "pour", "steep", "add-milk", "drink"],
        [("boil", "pour"), ("pour", "steep"), ("steep", "add-milk"), ("add-milk", "drink")],
    ),
    _task(
        "build-graph",
        "Build modules in dependency order. Modules: core, utils, api, cli, docs. "
        "Dependencies: utils needs core, api needs utils, cli needs api, docs needs api. "
        "Give an order that builds each module only after its dependencies.",
        ["core", "utils", "api", "cli", "docs"],
        [("core", "utils"), ("utils", "api"), ("api", "cli"), ("api", "docs")],
    ),
    _task(
        "house-build",
        "Build a house. Steps: foundation, framing, roof, wiring, drywall, paint. "
        "Rules: foundation before framing, framing before roof, framing before wiring, "
        "wiring before drywall, roof before drywall, drywall before paint. Give a valid order.",
        ["foundation", "framing", "roof", "wiring", "drywall", "paint"],
        [
            ("foundation", "framing"),
            ("framing", "roof"),
            ("framing", "wiring"),
            ("wiring", "drywall"),
            ("roof", "drywall"),
            ("drywall", "paint"),
        ],
    ),
]


# ── generated tasks (large-N, graduated difficulty) ───────────────────────────
# A fixed catalogue of random-but-deterministic DAG-ordering problems, so the
# suite has enough items to discriminate models reliably (the 6 themed tasks
# above are too few). Generated from a fixed seed, so the same tasks — and the
# same ids — appear on every run; scores stay comparable across runs. Labels are
# "n1".."nN" (digit-suffixed, word-boundary-safe, never collide with prose).

#: task id -> one known-valid topological order, for tests and debugging.
_GENERATED_SOLUTIONS: dict[str, list[str]] = {}


def generate_planning_tasks(count: int, *, seed: int = 1234) -> list[Task]:
    """Build ``count`` deterministic DAG-ordering planning tasks.

    Each task: pick a step count (5–8), take a fixed "true order" of labels, then
    add random precedence edges consistent with it (each edge goes from an
    earlier to a later step). The model must output any valid topological order;
    :func:`valid_ordering` accepts all of them. The true order is recorded in
    :data:`_GENERATED_SOLUTIONS`. Same ``seed`` → identical tasks every call.
    """
    rng = random.Random(seed)
    tasks: list[Task] = []
    for i in range(count):
        n = rng.randint(5, 8)
        labels = [f"n{k + 1}" for k in range(n)]
        order = labels[:]  # the canonical valid order is n1..nN
        # Add edges from earlier→later steps; density scales with n.
        edges: set[tuple[str, str]] = set()
        for _ in range(rng.randint(n, n * 2)):
            a = rng.randint(0, n - 2)
            b = rng.randint(a + 1, n - 1)
            edges.add((order[a], order[b]))
        # Guarantee the chain is connected enough to be non-trivial: link each
        # step to the next with some probability so orderings aren't wide open.
        for k in range(n - 1):
            if rng.random() < 0.5:
                edges.add((order[k], order[k + 1]))
        before = sorted(edges)
        task_id = f"gen-plan-{i:02d}"
        _GENERATED_SOLUTIONS[task_id] = order
        constraints = "; ".join(f"{x} before {y}" for x, y in before)
        problem = (
            f"You must order these steps: {', '.join(labels)}. "
            f"Constraints: {constraints}. Produce a valid order."
        )
        tasks.append(
            Task(id=task_id, prompt=problem + _FORMAT, grader=valid_ordering(labels, before))
        )
    return tasks


# The shipped suite: the themed tasks (readable) + a large generated batch (for
# statistical power). --limit on the runner subsamples for a quick pass.
PLANNING_SUITE = PLANNING_SUITE + generate_planning_tasks(24)
