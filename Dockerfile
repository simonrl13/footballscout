# uv is used only at build time (mounted, not copied): the runtime image starts uvicorn straight from the venv.
FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv

FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=from=uv,source=/uv,target=/bin/uv uv sync --frozen --no-default-groups --no-install-project
COPY scout ./scout
# Non-editable install, then drop the source copy so the installed package (with bytecode) is what gets imported.
RUN --mount=from=uv,source=/uv,target=/bin/uv uv sync --frozen --no-default-groups --no-editable && rm -rf /app/scout
# Bytecode for exactly what startup imports (stdlib included): start the server once as root and call /health, so
# Python writes __pycache__ for those modules only. The runtime user can't write it, and nothing else is compiled.
COPY docker/compile_startup.py /tmp/
RUN PUBLIC_DEMO=true /app/.venv/bin/python /tmp/compile_startup.py && rm /tmp/compile_startup.py \
    && useradd --create-home app
USER app
CMD ["/app/.venv/bin/uvicorn", "scout.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
