FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project
COPY scout ./scout
RUN uv sync --no-dev
CMD ["uv", "run", "--no-sync", "uvicorn", "scout.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
