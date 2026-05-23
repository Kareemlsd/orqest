"""Runtime agent spawning and tool discovery.

The autonomy module enables the orchestrator to design and spawn new agents
at runtime. An LLM produces an AgentSpec (structured output describing an
agent), and the AgentFactory hydrates it into a live BaseAgent. The
ToolRegistry provides discoverable tools.
"""
from orqest.autonomy.factory import AgentFactory, DynamicAgent
from orqest.autonomy.meta import ExecutionResult, MetaOrchestrator, SubTask, SubTaskResult, TaskDecomposition
from orqest.autonomy.registry import ToolInfo, ToolRegistry
from orqest.autonomy.spec import AgentSpec, GeneratedToolSpec, ToolSpec
from orqest.autonomy.tool_factory import DynamicToolFactory

# NOTE: orqest.autonomy.runtime (RuntimeTopologyDesigner + caches) and
# orqest.autonomy.topology_orchestrator (TopologyOrchestrator) are
# intentionally NOT re-exported here. Both transitively import from
# orqest.optimization.meta_agent (for TopologyDesign), and eagerly loading
# them at autonomy package init creates a cycle:
#     autonomy/__init__.py → runtime → optimization.meta_agent (mid-init)
#         ← optimization.topology ← autonomy.factory
# Use the explicit submodule path:
#     from orqest.autonomy.runtime import RuntimeTopologyDesigner, MemoryStoreCache
#     from orqest.autonomy.topology_orchestrator import TopologyOrchestrator
# This matches the import pattern used by other heavy batteries
# (e.g., `from orqest.compound import SubAgentTool`,
#        `from orqest.metacognition import StructuredOutputProtocol`).

__all__ = [
    "AgentFactory",
    "AgentSpec",
    "DynamicAgent",
    "DynamicToolFactory",
    "ExecutionResult",
    "GeneratedToolSpec",
    "MetaOrchestrator",
    "SubTask",
    "SubTaskResult",
    "TaskDecomposition",
    "ToolInfo",
    "ToolRegistry",
    "ToolSpec",
]
