"""Built-in alternate agent architectures.

Importing this package registers each alternate (orchestrator-worker,
evaluator-optimizer, planner-executor) into the architecture registry via the
``@register`` decorator on each class. The default ``reactive`` architecture
lives in agent.py and is registered when that module is imported.

agent.run_agent imports this package lazily (see agent._load_architectures) so
the alternates are available by name without creating an import cycle (these
modules import agent for its loop primitives).
"""

from . import evaluator_optimizer, orchestrator_worker  # noqa: F401
