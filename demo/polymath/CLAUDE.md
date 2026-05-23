# Polymath — Agent Instructions

## What This Is

Polymath is the flagship demo for [Orqest](../../CLAUDE.md). It's a
**desktop-class agent workspace**: chat on the left, dynamic dockview-
based workspace on the right, with the agent's cognition (confidence,
self-healing, memory, sub-agents) surfaced in the chrome instead of
hidden behind a chat box. Every novel Orqest feature ships with a
visible UI surface here.

**Stack:** FastAPI + pydantic-ai + Orqest backend; Next.js 16 + AI
SDK v6 + dockview-react + shadcn/AI Elements + Tailwind v4 frontend;
Postgres for session/message/tab state; per-session Docker sandbox
(shell + Python + optional Chromium-via-noVNC).

## Current state (as of 2026-04-26)

**All five Orqest novel features shipped end-to-end and surfaced in the
chrome:**

| Novel feature | Backend status | Visible surface |
|---|---|---|
| Runtime agent design | ✅ MetaOrchestrator + AgentFactory + AgentSpec | Agents tab — roster table with confidence bars, depth-of-spawn indent |
| Cognitive memory typology | ✅ semantic / episodic / procedural | Memory tab — galaxy SVG + 3-kind counts + filter + kind-tinted item list |
| Metacognition primitives | ✅ MetacognitionHook + LLMSelfRatingProtocol | **Cognitive Gutter** — 24px left rail per assistant turn, height-encoded confidence bar in 4 stops, tool/memory/sub ticks, amber live pulse |
| Self-healing primitives | ✅ Watchdog + FallbackModel + HealingRunner | Healing toasts (bottom-left stack) — `stall · 23s` / `loop · ×4` / `fallback · openai → anthropic` |
| Generative UI | ✅ 17 typed component classes + emit/update/remove tools | Workspace tabs — each `emit_component` opens a dockview tab; `metadata.target_tab_id` groups |

**Editorial design grammar (claude.ai/design redesign 2026-04-26):**
warm-neutral `oklch(0.165 0.006 60)` background, amber signal accent
`oklch(0.78 0.14 75)` (replaces the prior teal), Newsreader serif for
ideas / Inter Tight grotesk for body / JetBrains Mono for chrome,
hairline borders only (no shadows for depth), one accent per visible
region. The Cognitive Gutter is the design's through-line — it
replaces the per-message confidence pill and ties chat → tools →
memory into one continuous mind.

## Project structure

```
demo/polymath/
├── CLAUDE.md                  # this file
├── README.md                  # Quick-start (Docker compose), security note
├── docker-compose.yml         # postgres + backend + frontend + sandbox-builder
├── dev.sh                     # Local dev (no docker for backend/frontend)
├── .env.example
├── .claude/
│   ├── POLYMATH_ASSESSMENT_2026-04-25.md   # original audit before consolidation
│   └── CONSOLIDATION_COMPLETE_2026-04-25.md # running log of every wave through 2026-04-26
│
├── backend/                   # FastAPI + Orqest glue
│   └── polymath/
│       ├── server.py          # FastAPI app + router mounts
│       ├── orchestrator.py    # PolymathAgent(BaseAgent[PolymathState, str]) — the orchestrator
│       ├── agent.py           # back-compat shim re-exporting from orchestrator.py
│       ├── state.py           # PolymathState (session_id + plan)
│       ├── config.py          # PolymathConfig (frozen) + load_config + get_default_config
│       ├── runtime.py         # SessionRuntime cache + emit() helper
│       ├── workbench_factory.py # build_workbench(sid) → SessionRuntime; wires hooks + healing
│       ├── tab_respawn.py     # EventBus subscriber that auto-spawns system tabs
│       ├── session_metrics.py # Cumulative session usage aggregator
│       │
│       ├── tools/             # Agent-facing tools (pydantic-ai Tool wrappers)
│       │   ├── web.py         # web_search (Tavily) + web_fetch
│       │   ├── plan.py        # init_plan / update_plan
│       │   ├── memory.py      # remember / recall (emits memory.* events)
│       │   ├── fs.py          # read_file / write_file / edit_file / list_dir
│       │   ├── shell.py       # run_command / run_python_snippet
│       │   ├── browser.py     # browser_open_url / browser_click / browser_type (gated)
│       │   ├── report.py      # render_chart / markdown_to_pdf
│       │   ├── autonomy.py    # register_agent / invoke_agent / list_agents / spawn_analyst
│       │   ├── ui.py          # emit_component / update_component / remove_component
│       │   └── tabs.py        # open_tab / update_tab / close_tab
│       │
│       ├── routers/           # FastAPI routers
│       │   ├── sessions.py    # CRUD; GET returns cumulative_usage
│       │   ├── chat.py        # POST /chat/stream; emits metacognition.confidence + chat.turn.completed in on_complete
│       │   ├── events.py      # /events SSE sidecar
│       │   ├── snapshot.py    # /snapshot + /plan reconstruction from event ring buffer
│       │   ├── files.py       # /files (sandbox proxy)
│       │   ├── viewport.py    # /viewport_url (noVNC)
│       │   ├── artifacts.py   # /artifacts (chart + report files)
│       │   ├── takeover.py    # /takeover (pause/resume agent)
│       │   ├── ui.py          # /ui/event-types — manifest of SSE events frontend should subscribe to
│       │   ├── tabs.py        # /tabs CRUD (open/close/reorder/restore/focus)
│       │   ├── memory.py      # /memory grouped by kind — feeds the Memory tab
│       │   ├── autonomy.py    # /agents/roster — feeds the Agents tab
│       │   └── config_router.py # /config — feature flags
│       │
│       ├── sandbox/           # Per-session Docker container manager
│       ├── artifacts/         # Artifact persistence + Streaming
│       ├── db/                # SQLModel tables (Session, Message, Plan, Artifact, Tab)
│       └── system_prompts/orchestrator.md
│
└── frontend/                  # Next.js 16 + Tailwind v4
    └── src/
        ├── app/
        │   ├── layout.tsx
        │   ├── page.tsx       # Landing
        │   ├── globals.css    # Editorial dark tokens — see "Design tokens" below
        │   └── sessions/[id]/page.tsx  # Two-pane shell + 40px editorial top bar
        │
        ├── components/
        │   ├── chat/          # Cognitive Gutter, Message, ChatPane (editorial empty state),
        │   │                  # Composer (PromptInput toolbar), PlanHeader, ConfidenceBadge,
        │   │                  # ToolCard, ToolStrip (ChainOfThought), Sources, CheckpointDivider
        │   ├── computer/      # DockviewWorkspace (with EmptyWorkspaceState overlay),
        │   │                  # ComputerPane, panels/{Shell,Files,Browser,Editor,
        │   │                  # ChartGallery,Report,Memory,Agents,ComponentTab}Panel,
        │   │                  # TakeoverDialogModal, RecentlyClosedMenu, UndoCloseToast
        │   ├── memory/        # MemoryBrowser (galaxy + counts + filter), MemoryGalaxy, MemoryItem
        │   ├── agents/        # AgentRoster (table view, depth indent, confidence bars)
        │   ├── healing/       # HealingToasts (bottom-left stack)
        │   ├── ai-elements/   # Vendored shadcn-style: actions, inline-citation, context,
        │   │                  # chain-of-thought, checkpoint, prompt-input, message,
        │   │                  # reasoning, tool, sources, code-block, conversation, etc.
        │   ├── ui-renderers/  # Generative UI dispatcher: 12 typed renderers
        │   │                  # (markdown, vega_chart, mermaid, latex, json_viewer,
        │   │                  # sandboxed_html, layout, text, image, badge, button, input)
        │   └── ui/            # shadcn primitives (button, dialog, tabs, tooltip, …)
        │
        ├── hooks/             # useChat, useSidecar, usePlan, useArtifacts, useTabs,
        │                      # useChatMetrics, useMetacognition, useCognitiveGutterEvents,
        │                      # useMemory, useAgentRoster, useHealingEvents,
        │                      # useSessionMetrics, useRecentMemory, useFeatureFlags,
        │                      # SidecarProvider, UIComponentsProvider
        │
        ├── lib/               # api.ts (backendBase), events.ts (AgentEvent type)
        └── styles/dockview-polymath.css  # dockview theme override → Polymath tokens
```

## Running locally

The backend lives in `backend/.venv/`. The frontend uses `next dev`.
Postgres runs in docker-compose. There's a helper script `dev.sh`:

```bash
cd demo/polymath
./dev.sh up      # starts postgres + backend + frontend
./dev.sh restart # nuke + restart
./dev.sh down    # stop everything
./dev.sh logs    # tail backend + frontend logs
```

Then open `http://localhost:3000`. The agent uses the LLM model
configured in `.env` (`LLM_MODEL=openai:gpt-5.4` or similar) with
optional `POLYMATH_FALLBACK_MODELS=…` for the healing fallback chain.

Backend env: `OPENAI_API_KEY` required (or `ANTHROPIC_API_KEY` if the
model is Claude). Web search uses `ORQEST_WEB_PROVIDER=tavily` +
`ORQEST_WEB_API_KEY=tvly-…`. See `.env.example` for the full set.

**Feature gates** (default-on / default-off as noted):
- `POLYMATH_ENABLE_HEALING=1` (on) — healing watchdogs + fallback chain
- `POLYMATH_ENABLE_SANDBOXED_HTML=1` (on) — Layer-3 sandboxed HTML iframe component
- `POLYMATH_ENABLE_BROWSER=0` (off) — noVNC + Chromium are heavy; flip on for browser-driving demos
- `POLYMATH_ENABLE_SELF_RATING=1` (on) — +1 LLM call per turn for the per-message confidence badge
- `POLYMATH_USE_MCP=0` (off) — auto-discover MCP servers from `~/.claude.json` etc.

## Architecture cheatsheet

**Two panes, one window.** Left: chat (560px fixed). Right: dynamic
dockview workspace (fluid). 40px editorial top bar with diamond glyph
+ session id slug + plan-derived context label + token-usage ring +
`live`/`idle` indicator.

**Tab manifest = source of truth for the right pane.** A `Tab`
SQLModel persists every workspace tab; the dockview frontend hydrates
on mount via `GET /sessions/{sid}/tabs` and live-merges `tab.*` SSE
events. The agent has `open_tab` / `update_tab` / `close_tab` tools,
and `emit_component(metadata.target_tab_id=…)` groups components into
existing tabs. Auto-respawn middleware (`tab_respawn.py`) ensures
system surfaces (Shell / Files / Editor-per-path / Browser / Memory
/ Agents / Charts / Report) appear lazily on first relevant tool
activity. Tab kinds: `shell` / `files` / `browser` / `editor` /
`chart_gallery` / `report` / `memory` / `agents` / `component`.

**Generative UI is 3 layers.** Layer 1 — compositional primitives
(`layout`/`text`/`markdown`/`image`/`badge`/`button`/`input`).
Layer 2 — declarative grammars (`vega_chart`/`mermaid`/`latex`/
`json_viewer`). Layer 3 — sandboxed HTML escape hatch
(`sandboxed_html`, gated by `ENABLE_SANDBOXED_HTML`). The agent
emits any of these via `emit_component(component_type, data,
metadata?)`; the frontend dispatches via `UIComponentRenderer` against
a registered renderer map.

**The cognitive backbone shows up in the chrome** (this is what no
other agent product does):

- **Cognitive Gutter** (`components/chat/CognitiveGutter.tsx`) — 24px
  left rail per assistant turn. Confidence is the column the message
  stands on, encoded as bar height + 4-tier amber/muted/warn color.
  Tool calls are ticks; memory writes are dots; an amber pulse marks
  the live cursor.
- **Healing toasts** (`components/healing/HealingToasts.tsx`) —
  bottom-left transient stack for `healing.detection` /
  `healing.action` / `healing.retry_initiated` / `healing.model_fallback`
  / `healing.model_chain_exhausted` events.
- **Memory tab** (`components/memory/MemoryBrowser.tsx`) — galaxy SVG
  + 3-kind counts + filter + kind-tinted item list. Backed by
  `LocalMemoryStore.list_recent(memory_type=, limit=)`.
- **Agents tab** (`components/agents/AgentRoster.tsx`) — roster table
  with serif italic names, depth-of-spawn indent, kind-tinted
  confidence bars. Backed by `_load_sub_agents` reading from
  procedural memory entries that carry an `agent_spec` payload.

## Design tokens (editorial dark grammar — `globals.css`)

```css
.dark {
  --color-background:        oklch(0.165 0.006 60);   /* warm-neutral near-black */
  --color-foreground:        oklch(0.965 0.005 90);
  --color-surface-card:      oklch(0.205 0.006 60);
  --color-surface-elevated:  oklch(0.245 0.006 60);
  --color-surface-code:      oklch(0.185 0.006 60);
  --color-muted-foreground:  oklch(0.78 0.008 80);

  --color-accent:            oklch(0.78 0.14 75);     /* signal amber */
  --color-accent-hover:      oklch(0.72 0.13 70);
  --color-accent-subtle:     oklch(0.78 0.14 75 / 0.16);

  --color-border-subtle:     rgba(255,255,255,0.06);  /* structural */
  --color-border-default:    rgba(255,255,255,0.10);  /* interactive */
  --color-border-strong:     rgba(255,255,255,0.18);  /* focus */

  /* Kind colors — semantic / episodic / procedural / verified */
  --color-kind-semantic:     oklch(0.78 0.06 220);
  --color-kind-episodic:     oklch(0.72 0.10 290);
  --color-kind-procedural:   oklch(0.78 0.10 150);
  --color-warn:              oklch(0.7 0.16 30);

  /* Confidence stops (drives the gutter, ConfidenceBadge, AgentRoster bars) */
  --color-conf-high:  oklch(0.78 0.14 75);   /* ≥ 0.85 */
  --color-conf-mid:   oklch(0.62 0.13 65);   /* 0.65 – 0.85 */
  --color-conf-low:   oklch(0.58 0.008 80);  /* 0.45 – 0.65 */
  --color-conf-doubt: oklch(0.7 0.16 30);    /* < 0.45 */
}
```

Fonts: `Newsreader` (serif, ideas/headlines), `Inter Tight` (sans,
body), `JetBrains Mono` (chrome, labels, kbd hints). Loaded via
Google Fonts at the top of `globals.css`.

## Anti-slop discipline

Hard rules — apply to every new surface:

- **No avatars, no bubble tails, no `rounded-2xl`, no rainbow gradients.**
- One accent (amber) + neutral grayscale only. Saturated color used at
  most once per visible region.
- Hover-revealed actions only — never always-on toolbars.
- Mono 10–11px for chrome / metadata, sans 13–14px for body, serif for
  headings / quotes / agent names.
- No "AI is thinking..." prose; one Shimmer max per streaming turn
  (header line, not body).
- No emoji in default UI strings.
- No marketing copy in the empty state — the chat empty state is
  "What should we / *think through* today?" + remembered threads;
  nothing greets the user.

## Test discipline

Backend: 178 tests passing as of 2026-04-26 (`pytest tests/ -q` from
`backend/`). Every backend change ships with a test. Test suite runs
in ~10s against an in-memory SQLite engine (per-test fixture in
`tests/conftest.py`).

Frontend: `tsc --noEmit` from `frontend/` must be clean before any
commit. We have no jest/vitest setup — visual verification is
playwright-driven via ad-hoc agents (see
`/tmp/polymath-redesign-verify/`'s pattern).

## Where to read next

- `.claude/CONSOLIDATION_COMPLETE_2026-04-25.md` — running log of every
  wave shipped on 2026-04-25 → 04-26 (consolidation, stability,
  generative UI, tabs, dockview, cognitive surfacing, chat polish,
  editorial redesign). The most recent addendum at the bottom is the
  clearest "what just changed" summary.
- `.claude/POLYMATH_ASSESSMENT_2026-04-25.md` — the assessment that
  drove the consolidation. Useful historical context.
- `../../CLAUDE.md` — Orqest framework instructions (above this demo).
- `../../.claude/VISION.md` — strategic frame: the five novel
  features that define Orqest.
- `../../.claude/AUDIT_2026-04-25.md` — the audit that drove
  metacognition / healing / generative-UI implementation.

## Pending work

- **Phase 6 — docs + demo script + CI.** The README at this demo
  level still describes "under construction" / phase plan from
  pre-consolidation. Refresh + record a hero-scenario demo video.
  Tests exist; CI wiring doesn't.
- Production memory backend (Supabase pgvector — known gap).
- Edit-and-resend / branch on the chat — design accommodates it
  (`Checkpoint` divider exists), wiring is deferred.
- The Vega-Lite v5/v6 spec mismatch warning is cosmetic and persists.
- Next.js 16.1.1 dev-mode RSC `Set` serialization warning — framework
  internal, not actionable from app code.
