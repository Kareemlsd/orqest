# Orqest — How to Build With It

Orqest is a Python **library** for building agentic harnesses on top of pydantic-ai. It is **not** a runtime, server, framework with its own UI, or workflow engine. It is the plumbing imported into an existing application to wire in agent capabilities. [Polymath (`demo/polymath/`)](demo/polymath/) is one consumer that exercises every primitive end-to-end.

## Getting started

- **[Notebooks](notebooks/)** — start here if you're evaluating Orqest. A 12-notebook tour from cognitive substrate → meta-orchestrator → generative UI → orchestrated workflow → reasoning → optimization → topology search → runtime topology → dynamic tools → autonomous-coder combo.
- **[Examples](examples/)** — runnable per-primitive references.
- **[Concept docs](https://kareemlsd.github.io/orqest/concepts/agents/)** — per-subsystem deep dives.
- **[CLAUDE.md](CLAUDE.md)** — agent-instructions ground truth (file structure, public API, conventions).

## The litmus test that governs everything

> *"Core Orqest manages the **shape and flow** of intelligence; extensions manage the **matter and action** of the domain. Could a developer building a headless coding assistant use this without knowing what Polymath is?"*

When in doubt, less is more. **Pick the smallest surface that fits.**
