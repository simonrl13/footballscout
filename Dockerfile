FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
COPY --from=ghcr.io/astral-sh/uv:0.12.18@sha256:3adc3706091ce7c2fe595e669628caedd6d951551b92b258b7e7dbe06d9440bc /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY scout ./scout
RUN uv sync --frozen --no-dev && useradd --create-home app
USER app
CMD ["uv", "run", "--no-sync", "uvicorn", "scout.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
