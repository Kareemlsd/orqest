---
name: principles
description: Canonical development principles for the orqest codebase — Pragmatic-Programmer-rooted concrete rules (no import-time side effects, explicit deps, no input mutation, mapping-based dispatch, validate at boundaries, mock the model layer, async tests, crash early, max one level of inheritance, tracer bullets). Trigger whenever writing, reviewing, refactoring, or designing API surface in this repo; whenever planning a new battery; whenever evaluating a code change for merge; whenever a PR touches orqest/ or tests/. Apply these rules as guardrails — when in doubt, the rule wins.
---

# Orqest Development Principles

Guidelines rooted in *The Pragmatic Programmer*. Concrete rules — not abstract advice. Apply these to every change touching `orqest/` or `tests/`. When a rule conflicts with a local convenience, the rule wins; flag the conflict instead of bending it.

## Principles

### Orthogonality

- No side effects at import time. Module-level code defines names only.
- Functions accept dependencies as arguments, not via module globals.
- An agent's behavior is fully determined by its constructor arguments.
  Two agents in the same process with different providers must coexist.

### DRY

- If two functions differ only by a string literal, extract one parameterized function.
- State fields must have non-overlapping responsibilities.
- No "just in case" fields. Every field must be read somewhere.

### Reversibility

- Never mutate input data. Processors return new structures, not modified originals.
- Provider/strategy selection uses mappings, not if/elif chains. Adding a new
  option means editing data, not control flow.
- Error handling preserves information. The caller decides policy, not the framework.

### Design by Contract

- Validate at system boundaries (config loading, constructors, public entry points).
  Internal code trusts what was already validated.
- Fail early with a clear message. Missing config surfaces at startup, not mid-run.
- Guard string parsing. Validate expected formats before splitting or indexing.

### Test to Code

- Mirror source layout: `orqest/agents/base_agent.py` → `tests/agents/test_base_agent.py`.
- Every branch in routing/dispatch logic gets an explicit test.
- Tests must not require real API keys. Mock the model/provider layer.
- Use `pytest-asyncio` for async tests.

### Documentation Answers "Why"

- Do not restate code in English. No `# Add message to list` above `list.append()`.
- Docstrings explain intent and non-obvious decisions, not mechanics.
- Module docstrings state the module's responsibility and its relationship to
  neighbors — not a list of what functions it contains.

### ETC: Easy to Change

- Constructor parameters must not overlap. If a pre-built object is accepted,
  parameters that configure building that object become invalid — don't accept both.
- Prefer composition over configuration. New behavior belongs in a composable piece,
  not another `__init__` parameter.
- Keep the public API surface small. Internal helpers stay private.

### Shy Code (Tell, Don't Ask)

- Don't reach through objects. If you're chaining attribute access more than one level
  deep (e.g., `msg.parts[0].content`), you're coupled to someone else's internals.
- Modules only know their immediate collaborators. An agent doesn't know how a
  provider constructs its model — it receives a ready-to-use model.
- Expose operations, not structure. Instead of letting callers dig into state
  fields, provide methods that perform the needed action.

### Transforming Programming

- Think in pipelines: input → transform → transform → output.
- History processors are already a pipeline — extend this pattern to agent
  composition. Agents should be composable transformations, not stateful objects
  communicating through side effects.
- Prefer pure functions where possible. Side effects live at the edges.

### Crash Early

- A crashed program does less damage than a crippled one running with bad state.
- Never silently return `None` to hide a failure. Raise, log, and let the caller
  decide recovery policy.
- If config is missing or invalid, crash at startup — not halfway through a run.

### Inheritance Tax

- One level of inheritance (BaseAgent → ConcreteAgent) is fine.
- Beyond that, prefer protocols and composition. Don't stack abstract base classes.
- If a new feature tempts a second level of inheritance, use delegation or mixins instead.

### Tracer Bullets

- When building new features, get a thin end-to-end slice working first.
- Don't design the full abstraction in isolation. Get two agents talking through
  minimal wiring, then extract the pattern from working code.
- Tracer bullet code is kept — it's real production code, not throwaway prototyping.

### Pragmatic Paranoia

- You can't write perfect software. Design assuming your code will be misused.
- Defensive at boundaries, trusting internally (complements Design by Contract).
- External inputs (env vars, API responses, user state) are never trusted without
  validation. Internal function calls between validated layers can trust their inputs.
