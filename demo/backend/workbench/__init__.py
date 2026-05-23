"""Orqest Workbench — the canonical unified agentic demo.

This is THE reference implementation of an Orqest-powered app. Unlike the
five individual demos (each showing one slice), the Workbench demonstrates
the framework end-to-end:

- A single agent with a rich tool registry (search, compute, remember, recall)
- Real LocalMemoryStore persistence (SQLite)
- JSONTracer capturing execution timeline
- EventBus emitting lifecycle events
- HookRunner wiring before/after/error callbacks
- Structured output for artifacts + task plans in the same response
- A sidecar stream of Orqest-native events to the frontend (trace + memory + events)

Developers building Orqest apps should copy this pattern, not the individual demos.
"""
