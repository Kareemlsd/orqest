# Discovery Questions (Phase A)

Work through these in batches via the IDE's question UI — never all at once. Each carries a "why this matters" note. The developer's answers determine which Orqest components belong in the harness.

## Application context

1. **What does the application do?** (one sentence)
   *Why:* anchors the agent's goal in domain terms.

2. **Who uses it?** (end-user role)
   *Why:* shapes auth posture and UX expectations.

3. **What's the existing stack?** Frontend framework, backend framework, database, auth, deployment target.
   *Why:* dictates integration points.

4. **What language/runtime do the existing code conventions follow?** (sync vs async; type-hint coverage; lint config)
   *Why:* the agent code must conform, not impose.

## Agentic intent

5. **What task should the agent perform?** Conversational? One-shot? Long-running? Background batch?
   *Why:* drives whether you need streaming, persistence, or both.

6. **Is it user-triggered (request/response) or scheduled/event-driven?**
   *Why:* determines whether the agent runs inline with the request or in a worker.

7. **What does success look like?** A returned answer? A side effect on the DB? An emitted event? A rendered chart?
   *Why:* shapes the output type.

## Inputs / outputs

8. **What does the user (or caller) provide as input?** Free text? Structured form? An existing entity?
   *Why:* defines the agent's `state` shape.

9. **What should the agent return?** Text, structured data (Pydantic), UI components, side-effects on the app's DB, files — all of the above?
   *Why:* text → no UI; structured → typed Pydantic; UI → generative UI components; multiple → output type with optional fields.

## Tools

10. **What capabilities does the agent need?** Read existing app data? Write to the app's DB? Call internal services? Hit external APIs? Search the web? Use MCP servers?
    *Why:* defines the tool set; informs whether you need MCP client wiring.

11. **Read-only or write?**
    *Why:* write tools demand stricter approval / validation / audit.

## State & memory

12. **Does each invocation stand alone, or should the agent remember across sessions?**
    *Why:* skip memory entirely if no.

13. **If yes — what kind of memory?** Facts (semantic), past sessions (episodic), learned skills (procedural)?
    *Why:* each kind has its own storage and retrieval strategy in Orqest.

## Reliability & cost

14. **How critical is success rate?** Best-effort, mission-critical, regulated?
    *Why:* drives healing config, fallback chains, escalation paths.

15. **Per-request budget? Per-session? Don't-care?**
    *Why:* informs whether to wire any cost tracking.

## Observability

16. **Does the existing app already use OpenTelemetry, structured logs, or a tracing system?**
    *Why:* agent events should flow into the same stream, not parallel.

17. **Do you need a real-time event stream to the frontend (SSE / WebSocket)?**
    *Why:* determines whether to wire `sse_sidecar` and how to expose it.

## UI

18. **Does the agent need to render anything beyond text?** Charts, tables, forms, takeover dialogs? What's the existing frontend stack?
    *Why:* generative UI fits where the frontend already supports SSE-driven typed components. If the frontend is HTMX / vanilla / a non-supporting stack, return structured data instead.

## Auth & deployment

19. **Does the agent inherit the user's permissions, or run with a service identity?**
    *Why:* shapes how tools authorize; affects multi-tenant safety.

20. **Where will the agent run?** Same process as backend, separate worker, edge function?
    *Why:* same-process means in-flight cancellation works; worker means durable hand-off matters.

---

## How to ask

- Batch related questions (e.g., "Application context" together, "Tools" together).
- Always pair the question with the "why this matters" note if the developer asks.
- Stop and confirm understanding before moving on. The discovery output is a written summary the developer can correct.

## How to summarize

After the interview, restate the answers as a numbered list mirroring the questions. The developer either confirms or corrects. **Only proceed to Step 2 (codebase walk) once the summary is confirmed.**

Example summary:
```
1. App: e-commerce SaaS for boutique retailers
2. Users: shop owners (1 per workspace)
3. Stack: FastAPI 0.110 + SQLAlchemy 2 + Postgres 16 + React 18 (Tanstack Query)
4. Conventions: async backend, ruff lint, mypy strict
5. Task: agent summarizes user's recent orders + flags anomalies
6. Trigger: user-clicked button in dashboard
7. Success: returns Markdown summary; renders inline (no SSE today)
8. Input: user_id (from JWT)
9. Output: Pydantic with summary: str + anomalies: list[str]
10. Tools: read recent orders via existing app.orders.queries.get_recent_orders
11. Read-only
12. No cross-session memory
13. n/a
14. Best-effort (button retries on failure)
15. Per-request budget — keep cheap
16. App uses structlog; OTel export to Honeycomb
17. No real-time stream needed
18. Markdown rendered by react-markdown; no charts/forms
19. Inherits user JWT
20. Same process as backend
```
