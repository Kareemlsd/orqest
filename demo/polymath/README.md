# Polymath

The flagship demo for [Orqest](../../README.md) — a desktop-class
agent workspace where every novel framework feature ships with a
visible UI surface. Chat on the left; dockview-driven dynamic
workspace on the right; cognitive backbone (confidence, self-healing,
memory typology, sub-agent roster) on display in the chrome instead of
hidden behind a chat box.

> **Status:** all five Orqest novel features shipped end-to-end and
> surfaced in editorial dark grammar (claude.ai/design redesign,
> 2026-04-26). Backend 178/178 tests passing; frontend `tsc --noEmit`
> clean.

For the canonical "what's where" guide, read **[`CLAUDE.md`](./CLAUDE.md)**
(in this directory). For the full running log of every wave shipped,
read [`.claude/CONSOLIDATION_COMPLETE_2026-04-25.md`](./.claude/CONSOLIDATION_COMPLETE_2026-04-25.md).

## What Polymath proves about Orqest

It exercises every battery in the framework, simultaneously, in one
running app:

- **Runtime agent design** — `MetaOrchestrator` + `AgentFactory` +
  `AgentSpec` spawn specialist sub-agents mid-task; the **Agents tab**
  renders them as a roster with confidence bars and depth-of-spawn
  indent.
- **Cognitive memory typology** — semantic / episodic / procedural,
  each with a per-kind retrieval strategy. The **Memory tab** renders
  them as a galaxy + 3-kind counts + filter + kind-tinted item list.
- **Metacognition primitives** — `LLMSelfRatingProtocol` rates the
  agent's output after each turn; the **Cognitive Gutter** (24px left
  rail per assistant turn) encodes confidence as bar height in 4
  tiers, with tool-call ticks and memory-write dots.
- **Self-healing primitives** — `Watchdog` + `FallbackModel` +
  `HealingRunner` detect stalls/loops/regressions and switch model
  providers transparently. **Healing toasts** (bottom-left stack)
  surface the recovery in real time.
- **Generative UI** — 17 typed `UIComponentSpec` classes ship across
  3 layers (compositional / declarative / sandboxed). The agent emits
  any of them via `emit_component(...)`; each opens a dockview tab.

`Workbench`, `JSONTracer`, `EventBus`, `sse_sidecar`,
`LocalMemoryStore`, `web_search` / `web_fetch`, `MCPServerManager`
(optional) all power the rest of the surface.

## Quick start

The fastest path is the local-dev script (postgres in docker, backend
+ frontend on the host):

```bash
cd demo/polymath
cp .env.example .env
# Edit .env — at minimum set OPENAI_API_KEY (or ANTHROPIC_API_KEY for Claude)
# Optional: ORQEST_WEB_PROVIDER=tavily + ORQEST_WEB_API_KEY=tvly-…  (web search)
# Optional: POLYMATH_FALLBACK_MODELS=anthropic:claude-sonnet-4-6,openai:gpt-4.1
./dev.sh up
```

Then open `http://localhost:3000`. Click "Start a session". The agent
greets you with the editorial empty state — *"What should we / think
through today?"* — plus a "continuing memory" list of remembered
threads if you've used Polymath before.

The full docker-compose path also works (`docker compose up --build`)
and is the recommended setup for one-shot demos. See
[`docker-compose.yml`](./docker-compose.yml) for the four-service
topology.

**Services & ports:**

| Port | Service | What |
|---|---|---|
| 3000 | frontend | Next.js 16 + AI SDK v6 + dockview-react |
| 8000 | backend | FastAPI + Orqest agent loop + sandbox orchestrator |
| 5432 | postgres | Sessions, messages, plans, artifacts, **tabs** |
| —   | sandbox-builder | One-shot service that builds `polymath-sandbox:latest`. Per-session sandboxes are spawned by the backend on demand. |

## Architecture (one paragraph)

A 40px **editorial top bar** carries a diamond-glyph wordmark, slug
session id, plan-derived context label, token-usage ring, and a
`live`/`idle` indicator. Below it, two panes: **chat** (560px fixed,
with the Cognitive Gutter on every assistant turn) and **dockview
workspace** (fluid, drag-reorderable tabs). The agent's tool calls
spawn `kind='shell' | 'files' | 'editor' | 'browser' | 'memory' |
'agents' | 'chart_gallery' | 'report' | 'component'` tabs lazily;
the user can close, reorder, or restore any of them. Tab manifest is
Postgres-backed so reload returns to the same state. Every assistant
turn is rated post-stream by `LLMSelfRatingProtocol`; that rating
flows into the Cognitive Gutter's bar height. Healing watchdogs and
the fallback chain run in the background; their detections surface as
transient toasts.

## Hero scenario (after every wave shipped)

> *"Search the web for the top 3 vector DBs, run a small benchmark in
> the sandbox, and write me a PDF report with citations."*

- Plan tab populates with 4 subtasks
- Agents tab spawns an analyst row when the orchestrator delegates
- Multi-tool turns render as a `ChainOfThought` step list with
  inline `[1] [2] [3]` citation hover-cards
- A Vega chart pops into its own tab via `emit_component`
- Healing toast may appear if a tool stalls or the model falls back
- Each assistant turn carries a confidence bar in the gutter +
  metadata strip below (`12.3s · 4 tools · 1.2k tokens`)
- Final tab in the workspace: a PDF report viewer
- Memory tab gains a procedural entry tagged with the new skill

## Security note

The local-dev path mounts the host Docker socket into the backend so
the `SandboxManager` can `docker run` per-session containers. That
grants the backend container full root on the host. **Fine for
localhost development, not for any shared or deployed environment.**
Production would use a higher-isolation sandbox (Firecracker / gVisor)
and a restricted Docker proxy.

## License

Inherits Orqest's licence.

## Where next?

- [`CLAUDE.md`](./CLAUDE.md) — agent-instructions guide (the canonical
  read-first doc)
- [`.claude/CONSOLIDATION_COMPLETE_2026-04-25.md`](./.claude/CONSOLIDATION_COMPLETE_2026-04-25.md)
  — running log of every wave (consolidation, stability, generative
  UI, tabs, dockview, cognitive surfacing, chat polish, editorial
  redesign)
- [`.claude/POLYMATH_ASSESSMENT_2026-04-25.md`](./.claude/POLYMATH_ASSESSMENT_2026-04-25.md)
  — original audit that drove the consolidation
- [`../../CLAUDE.md`](../../CLAUDE.md) — Orqest framework instructions
- [`../../.claude/VISION.md`](../../.claude/VISION.md) — the five
  novel features that define Orqest
