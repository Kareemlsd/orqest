# SubAgentTool — bind a stateless sub-agent to an executor

Orqest agents often build *compound tools*: LLM-facing callables that
delegate a structured decision to a stateless sub-agent, execute the
decision against a real system (MCP pipeline, sandbox, HTTP API, …),
commit the result back onto long-lived session state, and optionally
refine the result when a quality check fails.

Before `SubAgentTool`, every consumer hand-wrote that pipeline — tens
of lines per tool, with hand-rolled refinement loops, manual state
mutations, and inconsistent reporting of "did a refinement fire?".
`SubAgentTool` captures the pattern in a single class so consumers
only write the domain-specific executor, state updater, and (optional)
evaluator.

## Minimal example

```python
import asyncio

from pydantic import BaseModel

from orqest.agents import BaseAgent
from orqest.compound import SubAgentTool
from orqest.compound.sub_agent_tool import EvalResult


class GeoOutput(BaseModel):
    code: str


class State:
    def __init__(self):
        self.mesh_code = ""
        self.quality = 0.0


# Sub-agent (stateless; produces a structured output)
class GeometryAgent(BaseAgent[State, GeoOutput]):
    async def _run_implementation(self, state: State, **kwargs) -> GeoOutput:
        # In real code this calls an LLM; here we fake it.
        note = kwargs.get("note", "")
        return GeoOutput(code=f"// mesh for: {note}")


async def run_pipeline(out: GeoOutput, state: State) -> dict:
    # Imagine MCP calls here producing a quality score
    return {"code": out.code, "quality": 0.8}


def update_state(result: dict, state: State) -> None:
    state.mesh_code = result["code"]
    state.quality = result["quality"]


def check_quality(result: dict) -> EvalResult:
    return EvalResult(passed=result["quality"] >= 0.5)


def refine_prompt(result: dict, prompt: str) -> str:
    return f"{prompt}\n\nPREVIOUS QUALITY {result['quality']} — improve."


tool = SubAgentTool(
    agent=GeometryAgent(...),
    executor=run_pipeline,
    state_updater=update_state,
    evaluator=check_quality,
    max_refinements=1,
    build_refinement_prompt=refine_prompt,
)


async def main() -> None:
    state = State()
    outcome = await tool.run(state, prompt="square plate")
    print(outcome.result, outcome.refined, outcome.iterations)
```

## When to reach for this

- You have a structured sub-agent that produces a plan/code/spec, and a
  deterministic executor that acts on that spec.
- You want quality-based refinement without hand-rolling a retry loop.
- You want best-effort semantics: a failed refinement keeps the
  original result rather than propagating an exception.
- You compose with [`run_with_retry`](../reference/agents.md#run_with_retry)
  at the outer tool boundary to handle *exceptions* separately from
  *quality failures*.

## Semantics — what `SubAgentTool` does and doesn't do

- **Does** run one (agent → executor → state updater) cycle per pass.
- **Does** fire up to `max_refinements` additional passes if an
  evaluator fails and a refinement-prompt builder is supplied.
- **Does** commit state after every pass so downstream readers see the
  best result reached, even if a later refinement throws.
- **Does not** wrap exceptions — raise from the sub-agent or executor
  to surface them to the caller (usually inside a `run_with_retry`
  block that enriches the prompt on failure).
- **Does not** fire `HookRunner` events by itself. Wire the outer
  compound-tool boundary with `EventBusPublishHook` for observability.

## Reference

::: orqest.compound.SubAgentTool
::: orqest.compound.SubAgentResult
