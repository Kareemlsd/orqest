# polymath-backend

FastAPI + Orqest backend for the Polymath demo. See
`demo/polymath/backend/` docs and `.claude/plans/mellow-twirling-bentley.md`
for the full plan.

## Run (host)

```bash
cd demo/polymath/backend
pip install -e .
OPENAI_API_KEY=sk-... POLYMATH_DATABASE_URL=postgresql+psycopg://... \
    uvicorn polymath.server:app --reload --port 8000
```

## Run (docker-compose)

From `demo/polymath/`: `docker-compose up --build`.
