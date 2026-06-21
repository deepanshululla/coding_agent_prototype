"""A reasoning suite: multi-step problems graded on the model's final answer.

Unlike toolcall (tool mechanics) and coding (does the code pass tests), this
suite isolates *reasoning* — arithmetic word problems, logic/constraint
deduction, sequences, age/rate problems — each with a single deterministic
answer. Tasks are graded on what the model *says* (an answer-grader), not on any
file, so a weak tool-caller isn't penalised for the reasoning axis.

All local and no-network. Every prompt ends with the same instruction so the
answer lands on the last line where :func:`exact_answer` looks for it.
"""

from evals.graders import exact_answer
from evals.harness import Task

#: Appended to every prompt so the gradeable answer is isolated on the last line.
_FORMAT = (
    " Reason step by step, then write the final answer ALONE on the last line — "
    "just the value, with no words, units, or punctuation."
)


def _q(problem: str) -> str:
    return problem + _FORMAT


REASONING_SUITE: list[Task] = [
    Task(
        id="apples",
        prompt=_q(
            "A store starts the day with 120 apples. It sells three quarters of "
            "them, then receives a delivery of 30 more. How many apples does it "
            "have now?"
        ),
        grader=exact_answer("60"),
    ),
    Task(
        id="train-distance",
        prompt=_q(
            "A train travels at 60 mph for 2.5 hours, then at 40 mph for 1 hour. "
            "How many miles does it travel in total?"
        ),
        grader=exact_answer("190"),
    ),
    Task(
        id="ordering",
        prompt=_q(
            "Alice is taller than Bob. Bob is taller than Carol. Carol is taller "
            "than Dan. Who is the shortest person?"
        ),
        grader=exact_answer("Dan"),
    ),
    Task(
        id="syllogism",
        prompt=_q(
            "All Bloops are Razzies. All Razzies are Lazzies. Therefore, are all "
            "Bloops necessarily Lazzies? Answer yes or no."
        ),
        grader=exact_answer("yes"),
    ),
    Task(
        id="sequence",
        prompt=_q("What is the next number in the sequence 2, 6, 12, 20, 30, ... ?"),
        grader=exact_answer("42"),
    ),
    Task(
        id="minutes",
        prompt=_q("How many minutes are there in 3.5 hours?"),
        grader=exact_answer("210"),
    ),
    Task(
        id="ages",
        prompt=_q(
            "Sam is twice as old as Tom. In 5 years, the sum of their ages will "
            "be 40. How old is Sam now?"
        ),
        grader=exact_answer("20"),
    ),
    Task(
        id="bat-and-ball",
        prompt=_q(
            "A bat and a ball cost $1.10 in total. The bat costs $1.00 more than "
            "the ball. How much does the ball cost, in cents?"
        ),
        grader=exact_answer("5"),
    ),
]
