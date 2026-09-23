# Project: Football Player Value Forecasting + Scouting Agent

## Goal
Portfolio project: a trained ML model that forecasts 12-month market value changes for football players, exposed through an LLM agent with tool calling and RAG over football news. It should demonstrate solid ML practice (no data leakage, proper baselines, explainability) and modern LLM engineering (tool use, retrieval).

## Tech stack
- Python 3.11+ managed with uv, pandas, LightGBM, SHAP, scikit-learn
- PostgreSQL + pgvector (structured player data AND news embeddings in one DB)
- FastAPI backend exposing tools
- Anthropic Claude API for the agent (tool calling)
- Next.js frontend (chat interface + player detail page with SHAP chart)
- Docker Compose for local dev (Postgres/pgvector, API)

## Layout
- `scout/data/`  – Transfermarkt loading, target construction (Phase 1)
- `scout/ml/`    – features, training, SHAP, evaluation (Phase 2)
- `scout/news/`  – Guardian ingestion, chunking, embeddings, retrieval (Phase 3)
- `scout/agent/` – Claude tool-calling loop (Phase 4)
- `scout/api/`   – FastAPI app
- `frontend/`    – Next.js app (Phase 5)
- `db/`          – SQL (init, schema)
- `data/raw/`    – Kaggle Transfermarkt CSVs (downloaded manually by the user, gitignored)
- `tests/`

## Phases (one at a time, then stop and summarize for review)
0. Scaffolding — done
1. Data and target: load Kaggle Transfermarkt CSVs from `data/raw/` into Postgres (inspect actual columns first). Target = log(value_future / value_now) where value_future is the next valuation between t+365 and t+425 days; drop snapshots without one. EDA notebook: target distribution, coverage by league/season, value curves by age.
2. Features and model: point-in-time features only (age, position, contract months left, minutes last 6/12m + trend, goal contributions/90, league, club strength, 6m value momentum). Time-based split (train ≤2022, val 2023, test 2024+), never random. Baselines: no-change and linear. Metrics: MAE/RMSE on log change + directional accuracy. LightGBM + SHAP, saved model, per-prediction explanation function. Evaluation report with 5 case studies.
3. News RAG: Guardian Open Platform API (football), key from .env, respect terms, no other scraping. Chunk, embed, store in pgvector with date/URL/matched players & clubs. Retrieval: metadata filter first, then semantic search, recency boost.
4. Agent and API: tools `get_player`, `predict_value_change`, `search_players`, `search_news`. Claude tool-calling agent that cites model vs. news sources and states values are Transfermarkt estimates, not transfer fees. Streaming chat endpoint.
5. Frontend: Next.js chat page + player page (value history, predicted change, SHAP chart).

## General rules
- Write tests for target construction and the feature pipeline, especially tests proving there is no future data leakage.
- Keep secrets in .env; never hardcode keys.
- Prefer simple, readable code over clever abstractions.
- If something in the data doesn't match these assumptions, stop and tell the user instead of guessing.
- After each phase, update the README with what was built and how to run it.
