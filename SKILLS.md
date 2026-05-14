# Orqest — How to Build With It

> **The canonical playbook lives in the [`orqest` skill folder](.claude/skills/orqest/SKILL.md).** This file is a top-level pointer.

Orqest is a Python **library** for building agentic harnesses on top of pydantic-ai. It is **not** a runtime, server, framework with its own UI, or workflow engine. It is the plumbing imported into an existing application to wire in agent capabilities. [Polymath (`demo/polymath/`)](demo/polymath/) is one consumer that exercises every primitive end-to-end.

## For Claude Code (or any agentic IDE)

Use the bundled skill at [`.claude/skills/orqest/`](.claude/skills/orqest/). It contains:

- **[`SKILL.md`](.claude/skills/orqest/SKILL.md)** — the operating procedure: discovery → codebase walk → minimal surface → integration plan → tracer-bullet build → `AGENT_HARNESS.md`
- **[`references/`](.claude/skills/orqest/references/)** — discovery questions, codebase-walk patterns, eight named pattern recipes, the Vercel AI SDK + Orqest integration recipe (Polymath pattern), the public API surface, anti-patterns, extension patterns, and the required `AGENT_HARNESS.md` output template
- **[`assets/`](.claude/skills/orqest/assets/)** — Python boilerplate (`agent_module_template/`) and React frontend hooks (`frontend_hooks/`) extracted from Polymath, generic-ified for reuse
- **[`scripts/scaffold_agent.py`](.claude/skills/orqest/scripts/scaffold_agent.py)** — CLI that lays down the agent module skeleton into a target project

The skill is also packaged as [`orqest.skill`](.claude/skills/orqest.skill) in the same directory and symlinked at `~/.claude/skills/orqest` for global Claude Code availability.

## For human developers

Read the skill's [`SKILL.md`](.claude/skills/orqest/SKILL.md) — it's written for an LLM coding assistant but the same workflow works for humans. Then dive into:

- The eight pattern recipes in [`references/recipes.md`](.claude/skills/orqest/references/recipes.md)
- The [Vercel AI SDK integration guide](.claude/skills/orqest/references/ai_sdk_integration.md) if you're building a Next.js / React frontend
- The [concept docs](docs/concepts/) at the MkDocs site for per-subsystem deep dives

## For framework contributors

- [`CLAUDE.md`](CLAUDE.md) — agent-instructions ground truth (file structure, public API, conventions)
- [`.claude/ARCHITECTURE.md`](.claude/ARCHITECTURE.md) — extensibility playbook (10 named extension patterns)
- [`.claude/PRINCIPLES.md`](.claude/PRINCIPLES.md) — Pragmatic Programmer rules canonical for this codebase
- [`.claude/VISION.md`](.claude/VISION.md) — strategic frame
- [`CHANGELOG.md`](CHANGELOG.md) — `0.1.0` (Phases 2–5) + `0.2.0` (Waves 1–3 cognitive substrate)

## The litmus test that governs everything

> *"Core Orqest manages the **shape and flow** of intelligence; extensions manage the **matter and action** of the domain. Could a developer building a headless coding assistant use this without knowing what Polymath is?"*

When in doubt, less is more. **Pick the smallest surface that fits.**
