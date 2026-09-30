FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
COPY --from=ghcr.io/astral-sh/uv:0.12.18@sha256:3adc3706091ce7c2fe595e669628caedd6d951551b92b258b7e7dbe06d9440bc /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY scout ./scout
RUN uv sync --frozen --no-dev && useradd --create-home app
USER app
CMD ["uv", "run", "--no-sync", "uvicorn", "scout.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
