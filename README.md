# Scout — Football Player Value Forecasting + Scouting Agent

Forecasts 12-month Transfermarkt market-value changes with LightGBM + SHAP and exposes them through a Claude tool-calling agent with RAG over Guardian football news.

> Values are Transfermarkt crowd estimates, not real transfer fees.

## Status
- [x] Phase 0: scaffolding (Postgres + pgvector, FastAPI `/health`)
- [ ] Phase 1: data and target
- [ ] Phase 2: features and model
- [ ] Phase 3: news RAG
- [ ] Phase 4: agent and API
- [ ] Phase 5: frontend

## Layout
```
scout/data    data loading + target        scout/ml     features, training, SHAP
scout/news    Guardian ingestion + RAG      scout/agent  Claude agent loop
scout/api     FastAPI app                   frontend/    Next.js (Phase 5)
db/           SQL                           data/raw/    Kaggle CSVs (not committed)
```

## Setup
Requires [uv](https://docs.astral.sh/uv/) and Docker.

```sh
cp .env.example .env          # fill in keys when later phases need them
uv sync                       # create .venv with deps
docker compose up -d db       # Postgres 16 + pgvector
```

## Run
```sh
# API locally (reads DATABASE_URL from your shell/.env)
uv run --env-file .env uvicorn scout.api.main:app --reload
# or everything in Docker
docker compose up --build

curl http://localhost:8000/health   # {"status":"ok","db":"ok"}
```

## Test
```sh
uv run pytest
```
