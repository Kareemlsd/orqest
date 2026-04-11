"""Runtime agent spawning and tool discovery.

The autonomy module enables the orchestrator to design and spawn new agents
at runtime. An LLM produces an AgentSpec (structured output describing an
agent), and the AgentFactory hydrates it into a live BaseAgent. The
ToolRegistry provides discoverable tools.
"""
from orqest.autonomy.factory import AgentFactory, DynamicAgent
from orqest.autonomy.meta import ExecutionResult, MetaOrchestrator, SubTask, SubTaskResult, TaskDecomposition
from orqest.autonomy.registry import ToolInfo, ToolRegistry
from orqest.autonomy.spec import AgentSpec, ToolSpec

__all__ = [
    "AgentFactory",
    "AgentSpec",
    "DynamicAgent",
    "ExecutionResult",
    "MetaOrchestrator",
    "SubTask",
    "SubTaskResult",
    "TaskDecomposition",
    "ToolInfo",
    "ToolRegistry",
    "ToolSpec",
]
