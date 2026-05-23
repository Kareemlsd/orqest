---
name: polymath-research
description: Bootstrap a Polymath-style research engine on Orqest for a specific domain. Use when a developer wants an agentic system that does literature synthesis + experiment running + persistent memory for a research area they care about (the canonical example: dynamical systems / Koopman / world models, but the pattern generalises to any domain where there's an arxiv firehose + small reproducible experiments + a growing concept graph). The skill walks through tool selection, memory schema for the domain, system-prompt repointing, and the test-driven dogfood loop. Outputs a working Polymath fork specialised for the domain. Trigger when the user mentions "research engine", "personal research assistant", "literature synthesis agent", a research domain + "agent", "dogfood research workflow", or extending Polymath for a new domain.
---

# Polymath-Research — Bootstrap a Domain-Specific Research Engine

A pattern for turning Polymath (the Orqest flagship demo) into a research engine that an individual researcher uses *daily* for a specific domain. Not a generic chatbot, not a literature summariser — a substrate that reads primary sources, runs small experiments, remembers across sessions, and produces notes the researcher would write themselves.

> **The litmus test:** *"Would I, the researcher, reach for this tool on Monday morning to answer a real question I have? Would the output be something I'd save and reference next week?"*
> If no, the engine isn't done. Generic research-assistant chatbots fail this test universally; a well-pointed Polymath instance passes it.

## When to invoke this skill

- The developer wants Polymath specialised for a research domain they care about (`world models`, `protein folding`, `quantitative finance`, `climate modelling`, `theorem proving`, `algorithmic trading`, anything with primary literature + small experiments).
- They have an existing Polymath checkout (or are willing to clone one) and want to repoint it.
- They're frustrated by generic research assistants because the domain-specific judgment isn't there.

If the developer wants to build a generic Orqest agent (not Polymath-shaped, not research-focused), use the [`orqest` skill](../orqest/SKILL.md) instead. This skill assumes Polymath as the substrate.

## What the pattern looks like (the bones)

Every Polymath-Research instance has the same five bones; what varies per domain is the *flesh*:

1. **Primary-source tools** — domain-specific search + fetch (`arxiv_search` for ML/physics; `pubmed_search` for biomed; `ssrn_search` for finance; `crossref_search` for general academic).
2. **Source extraction** — pull structured text out of papers (PDF + HTML); domain-specific helpers for equations / tables / code where the literature relies on them.
3. **Citation graph** — Semantic Scholar / OpenAlex / ADS to traverse "what cites this" and "what this cites".
4. **Experiment runner** — structured wrapper over the per-session sandbox for running small numerical experiments in the domain (Koopman fits on dynamical systems; PyTorch on toy networks; data analysis with pandas; whatever's runnable in <5 min on a laptop).
5. **Cognitive memory** — `LocalMemoryStore` configured with an embedder, with system-prompt-enforced discipline for writing to `semantic` (concepts), `episodic` (sessions), `procedural` (recipes).

Everything else — `Workbench`, `MetaOrchestrator`, `RefinementLoop`, `WatchdogHook`, `EnrichedOutput`, `MetacognitionHook`, generative UI components, the Cognitive Gutter — comes for free from Polymath/Orqest. You don't build them; you wire them.

## Operating procedure

### Step 1 — Discovery: interview the researcher (REQUIRED, no skipping)

Ask the developer to answer these in their voice, not aspirationally:

1. **Domain.** "What's the research area, in one sentence? What sub-area are you in this month?"
2. **Daily question.** "What's a real question you'd want answered THIS WEEK?"
3. **Primary sources.** "Where does the literature live? (arxiv? journal X? a specific preprint server? books?)"
4. **Experiments.** "What does a small experiment in your domain look like? (Train an NN? Run a simulation? Compute a statistic?) How long does one take to run on a laptop?"
5. **Existing tools.** "What are you using TODAY for this work? (Notion? Obsidian? Cursor + ChatGPT? Jupyter notebooks?) What hurts about that?"
6. **Output shape.** "When you're satisfied with a research session, what's the artifact? A note? A plot? A piece of code? A decision?"
7. **Frequency.** "Daily, weekly, ad-hoc?"

**Hard rule:** every tool added in Step 3 must trace back to an answer from Step 1. If you can't cite the answer, don't include it.

### Step 2 — Inventory: existing Polymath state

Read what's already there:

```bash
# In the Polymath repo
cd demo/polymath/backend
ls polymath/tools/                     # what tools exist
cat polymath/orchestrator.py           # what's wired
cat polymath/system_prompts/orchestrator.md   # current persona
ls polymath/.claude/                   # any prior research-mode docs
```

Polymath ships generic tools (`web_search`, `web_fetch`, `read_file`, `write_file`, `run_command`, `run_python_snippet`, plus the cognitive UI tools). The research mode adds 4–5 domain-specific tools on top and rewrites the system prompt.

### Step 3 — Tool selection (the 5 bones, instantiated for the domain)

| Bone | What to add per domain |
|---|---|
| **Primary-source search** | Pick the API. ML/physics → `arxiv` package. Biomed → `pubmed`/`entrez`. Finance → SSRN / arxiv-q-fin. Cross-domain → `crossref` package. |
| **Source extraction** | `pypdf` for general PDF; arxiv HTML fallback for cleaner LLM input; consider `pymupdf4llm` for math-heavy literature (better equation preservation). |
| **Citation graph** | `semanticscholar` (free tier, ~100 req/min) covers most domains. `pyalex` for OpenAlex if you want license-free. ADS for astrophysics. |
| **Experiment runner** | Always a wrapper over `run_python_snippet`/`SandboxManager.exec`. Contract: program prints final JSON to stdout, saves plots to `/workspace/experiments/`. Domain-agnostic at the runner level; the agent's experiment code is domain-specific. |
| **Cognitive memory embedder** | OpenAI `text-embedding-3-small` (cheap, good default). Self-hosted alternative: `nomic-embed-text` via Ollama. The embedder makes the difference between brittle FTS5-LIKE recall and real concept similarity. |

Each tool follows the existing Polymath tool conventions (see `demo/polymath/backend/polymath/tools/web.py` as the reference template):

- `async def _toolname(ctx: RunContext[PolymathState], ...) -> str:`
- Wrap with `Tool(_toolname, name="toolname")` at module bottom
- Get config via `get_default_config()`
- Try/except → `emit("tool.<name>.error", ...)` → `return json.dumps({"error": ...})`
- Emit `started` / `completed` event pairs
- Google-style docstrings; `Annotated[..., "description"]` for params

### Step 4 — System-prompt repointing

The single most important change. Polymath's default prompt frames it as a "general-purpose autonomous agent." Research mode reframes as "research collaborator on [DOMAIN]."

Edit `demo/polymath/backend/polymath/system_prompts/orchestrator.md`. Surgical changes only:

1. **Opening paragraph** — name the domain explicitly. "You are Polymath, a research collaborator specialised in dynamical systems / world models / Koopman theory / model predictive control."
2. **Tool palette section** — promote the new domain-specific tools to "use FIRST" status; demote `web_search` to "for non-primary-source contexts".
3. **Add a "Research discipline" section** with:
   - Ground every claim in a specific source + section/page
   - Preserve math (don't paraphrase equations; emit LaTeX components)
   - Be skeptical of papers' own claims; flag hand-waves
   - Surface contradictions across sources
   - Call out uncertainty honestly (the cognitive gutter MUST track real evidence)
4. **Strengthen the memory-write rules** — mandate 2-5 `remember(memory_type="semantic", ...)` + 1 `episodic` + any `procedural` recipes per non-trivial turn. Without this, the agent forgets to write back and the engine doesn't compound.

Keep all the existing sections about plan board, sandbox, generative UI, tabs — they all apply unchanged to research workflows.

### Step 5 — Embedder + memory schema

In `demo/polymath/backend/polymath/workbench_factory.py`, configure the `LocalMemoryStore` with an embedder:

```python
from polymath.embedder import maybe_make_embedder

memory = LocalMemoryStore(
    db_path=cfg.MEMORY_DIR / f"{session_id}.db",
    embedder=maybe_make_embedder(),
)
```

`polymath/embedder.py` is a thin wrapper over OpenAI's embeddings API (graceful no-op when no key). Other backends are interchangeable.

Memory schema convention (system prompt enforces; the schema itself doesn't):

- **semantic**: concepts, definitions, claims. Include source citation. `"EDMD = Extended Dynamic Mode Decomposition; lifts state via dictionary of observables before fitting linear operator; converges to Koopman operator as dictionary → full basis. (Williams et al. 2015, §2.3)"`
- **episodic**: session-summary entries with date + outcome. `"2026-05-16 session: surveyed Koopman scaling approaches; found 4 lineages (Deep Koopman, EDMD-DL, kernel methods, neural-spectral); open question whether kernel methods scale to PDE-class systems."`
- **procedural**: reusable how-to. `"How to evaluate Koopman approximation on 3D nonlinear system: (1) generate trajectory data from known ODE, (2) lift state via dictionary, (3) fit operator, (4) predict 50 steps, (5) compute prediction-error vs horizon curve, (6) compare against true dynamics."`

### Step 6 — The first dogfood session

This is where research engines live or die. Do NOT publish, document, or share until ONE real research session has been completed end-to-end.

Pick the developer's `Daily question` from Step 1. Fire it at the engine. Watch:

- **Plan board** populates (3–5 task decomposition)
- **Tool strip** shows primary-source tools called (not just web_search)
- **Cognitive gutter** shows confidence that VARIES (high on definitions, lower on contested claims)
- **Memory tab** grows with new semantic + episodic entries
- **Output** is a structured artifact (markdown component) with inline citations
- **The output is something the researcher would actually use**

After: triage the top 3 papercuts. Those become the next iteration. Repeat until the developer would use it daily without prompting.

### Step 7 — Document (REQUIRED OUTPUT)

After the engine has produced one useful session, write `RESEARCH_ENGINE.md` in `demo/polymath/`:

```markdown
# Polymath Research Engine — [DOMAIN]

## Domain
[One paragraph: what this engine researches.]

## Tools added
[List of domain-specific tools, with one-line purpose each.]

## Memory schema
[How semantic / episodic / procedural map to this domain.]

## First dogfood sessions
[Dates + queries + what worked, what didn't. Update after each session.]

## Open papercuts
[Triage list from the last session.]
```

This becomes the iteration target. Every session that finds a papercut updates the list; every iteration burns down the list.

## Common pitfalls

1. **Skipping discovery.** "I'll figure out the tools later" → you build a generic chatbot. Discovery is what separates a research engine from a Cursor-with-arxiv-tab.
2. **Building the experiment runner before the literature loop works.** Lit synthesis is the always-needed bone; experiment is the discovery moat. Get literature right first.
3. **Forgetting to enforce memory writes in the prompt.** The agent will call `recall` but not `remember`. Without writes, the engine stays stateless across sessions — every session is Day 1. This is the most common silent failure.
4. **Treating it as a launch deliverable.** Research engines compound over months. The first session SHOULD feel underwhelming compared to the dream; the tenth session is when the value shows up. Don't ship the first session as "v1.0".
5. **Not configuring an embedder.** Without one, semantic recall falls back to FTS5 LIKE which doesn't work on free-text concept queries. The agent will appear to have memory but not be able to use it.
6. **Reasoning + tools on OpenAI gpt-5.x.** Function tools + `reasoning_effort` together require the Responses API. Polymath defaults to chat/completions. Use Anthropic for reasoning + tools, or switch to `openai-responses:gpt-5.4` if you really need gpt-5 with thinking.

## Worked example: dynamical systems / world models / Koopman

See `demo/polymath/backend/polymath/tools/{arxiv,pdf,citations,experiment}.py` for the four tools added to specialise Polymath for this domain. See `demo/polymath/backend/polymath/system_prompts/orchestrator.md` for the repointed system prompt. The first dogfood session is the Koopman literature scan: *"What are the current approaches to scaling Koopman to high-dim systems and what are their failure modes?"*

This is the canonical reference implementation. Read the four tool files end-to-end before adding your domain-specific tools — they're <300 lines each and demonstrate every convention this skill describes.

## When you're done

The deliverable is a Polymath fork (or branch) where:

- 4–5 domain-specific tools live under `backend/polymath/tools/`
- The system prompt is repointed
- The embedder is wired
- Memory schema is enforced via system prompt
- ONE real research session has produced a useful artifact
- `RESEARCH_ENGINE.md` documents what's there + what's next

Hand off to the developer with: *"This is yours now. Use it every Monday morning for the next 4 weeks. Triage the papercuts each week. The engine compounds."*
