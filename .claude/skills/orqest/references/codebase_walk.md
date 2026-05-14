# Codebase Walk (Phase B)

Use the IDE's `Read`, `Grep`, `Glob`, and `Bash ls` tools. The patterns below identify what the existing app already provides — Orqest must conform to those, not impose its own conventions.

## Stack identification

```bash
ls -la
cat pyproject.toml 2>/dev/null
cat package.json 2>/dev/null
cat requirements.txt 2>/dev/null
cat Cargo.toml 2>/dev/null
```

**Conclude:** the framework (FastAPI / Django / Flask / Next.js / Express / ...) and the major libraries. The agent code lives in this language and follows these dependencies.

## Entry points

### Python / FastAPI / Flask
```bash
grep -rn "FastAPI\|Flask\|@app\." --include="*.py" -l | head
grep -rn "router = APIRouter\|@router\." --include="*.py" -l | head
grep -rn "async def" --include="*.py" -l | wc -l   # async coverage
```

### Django
```bash
ls */urls.py
grep -rn "@api_view\|@action\|class.*View(" --include="*.py" -l | head
```

### Node / Express / Hono / Fastify
```bash
grep -rn "express()\|app\.get\|app\.post\|new Hono" --include="*.{js,ts}" -l | head
```

### Next.js
```bash
ls app/api/ pages/api/ 2>/dev/null
grep -rn "export.*POST\|export.*GET" app/ pages/ 2>/dev/null | head
```

**Conclude:** where existing route handlers / API endpoints / CLI commands live. The agent will be invoked from one of these — match the existing handler shape (sync vs async, return-shape, error envelope).

## Auth layer

```bash
grep -rn "Depends\|get_current_user\|@require_auth\|jwt\|session\|csrf_token" --include="*.py" -l | head
grep -rn "useSession\|getServerSession\|withAuth\|getUser" --include="*.{ts,tsx}" -l | head
```

**Conclude:** how the app validates users. The agent inherits this validation; never add a parallel auth path.

## Data layer

```bash
grep -rn "sqlalchemy\|prisma\|django.db.models\|sqlmodel\|drizzle\|knex\|typeorm" -l | head
ls migrations/ db/ schema.prisma 2>/dev/null
cat alembic.ini 2>/dev/null
```

**Conclude:** the ORM / queries the agent might need. The agent reads / writes through the existing data layer — never bypass.

## Async patterns

```bash
# Python
grep -c "async def" $(find . -name "*.py" 2>/dev/null | head -20) 2>/dev/null | sort -t: -k2 -nr | head
grep -rn "asyncio\|trio\|anyio\|uvloop" --include="*.py" -l | head
```

**Conclude:** is the codebase async-native? If sync (Django sync views, Flask without `flask[async]`), the agent path needs an async boundary at the entry point (`asyncio.run` inside the handler, or a sync-to-async bridge like `asgiref.sync.async_to_sync`).

## Existing observability

```bash
grep -rn "loguru\|structlog\|opentelemetry\|sentry_sdk\|datadog" --include="*.py" -l | head
ls .env .env.example 2>/dev/null
grep -E "OTEL_|OTLP_|SENTRY_|DD_" .env* 2>/dev/null
```

**Conclude:** log format, tracer, metrics. Agent events should flow into the same stream. Don't ship a parallel observability stack — wire `EventBus.subscribe_all` to forward Orqest events into the existing tracer.

## Existing UI

```bash
ls src/components/ frontend/src/ web/src/ app/ 2>/dev/null
cat package.json 2>/dev/null | grep -E "react|vue|svelte|htmx|alpinejs|stimulus" | head
grep -rn "EventSource\|WebSocket\|SSE\|useChat\|@ai-sdk" --include="*.{ts,tsx,js,jsx}" -l | head
```

**Conclude:**
- The component library (shadcn, MUI, Mantine, Chakra, vanilla, ...)
- State management (Tanstack Query, SWR, Zustand, Redux, Pinia, ...)
- Existing real-time channels (SSE / WebSocket / polling)
- AI SDK presence (if `useChat` already exists, plug into it; if not, decide whether to introduce it — see `references/ai_sdk_integration.md`)

If the frontend doesn't speak SSE today, generative UI requires *introducing* SSE — that's a meaningful infra decision. Surface it explicitly.

## Frontend → backend protocol

```bash
grep -rn "fetch(\|axios\.\|ofetch\|trpc\|hono\.client\|graphql\b" --include="*.{ts,tsx}" -l | head
```

**Conclude:** request shape (REST, tRPC, GraphQL, SSE, WebSocket). The agent endpoint matches the existing convention.

## CI / test setup

```bash
ls .github/workflows/ .gitlab-ci.yml .circleci/ 2>/dev/null
cat .github/workflows/*.yml 2>/dev/null | grep -E "pytest|jest|mypy|ruff|eslint|biome|tsc" | head
ls tests/ test/ __tests__/ 2>/dev/null
cat pyproject.toml 2>/dev/null | grep -E "ruff|mypy|pytest"
```

**Conclude:** the test framework and lint config. New agent code follows the existing conventions, not Orqest's pyproject preferences.

## Deployment target

```bash
ls Dockerfile docker-compose.yml fly.toml vercel.json render.yaml .ebextensions/ 2>/dev/null
cat Procfile 2>/dev/null
```

**Conclude:** where the app runs in production. Affects whether you can use SSE (some serverless platforms have hard timeouts), whether long-running agents are viable, whether subprocess sandboxing works.

## Quick summary template

After the walk, restate findings as a 5–7 line summary:

```
Stack: <framework> + <ORM> + <DB> + <frontend>. <async/sync> backend.
Auth: <auth mechanism>; routes use <pattern>.
Observability: <logger> + <tracer> with export to <destination>.
Frontend: <framework> with <state mgmt>; <SSE present|no SSE today>.
Tests: <test framework> + <lint config>.
Existing patterns: <conventions to match>.
Deployment: <target> (relevant constraints: <e.g. serverless timeout>).
```

The developer either confirms or corrects. Then proceed to Step 3 (Minimal Surface Selection).

## What NOT to assume

- Don't assume the app uses pydantic-ai / Orqest conventions just because the developer wants Orqest. They might be migrating from raw OpenAI SDK calls; their style differs.
- Don't assume async if you saw one `async def` in 200 sync functions. Look at the *handlers* — that's the dimension that matters for agent integration.
- Don't assume the frontend has SSE just because `EventSource` appears once. Verify it's wired into a render loop.
- Don't assume the developer wants every Orqest battery just because the codebase *could* support them. Stick to the discovery answers.
