FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY scout ./scout
RUN uv sync --frozen --no-dev && useradd --create-home app
USER app
CMD ["uv", "run", "--no-sync", "uvicorn", "scout.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
