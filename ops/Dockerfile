FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_NO_PROGRESS=1 \
    UV_CONCURRENT_DOWNLOADS=4 UV_HTTP_TIMEOUT=90 UV_HTTP_RETRIES=5 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN pip install --no-cache-dir uv==0.11.7 && \
    useradd --uid 10001 --create-home app
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --extra platform --no-dev --no-install-project
COPY src ./src
COPY scripts ./scripts
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --extra platform --no-dev
COPY rules ./rules
COPY fixtures ./fixtures
COPY skills ./skills
COPY _shared ./_shared
COPY templates ./templates
COPY migrations ./migrations
COPY alembic.ini ./
COPY ops/setup_checkpoint.py ./ops/setup_checkpoint.py
COPY ops/verify_object_references.py ./ops/verify_object_references.py
RUN mkdir -p /app/.tradecase/objects /app/.tradecase/work && chown -R app:app /app/.tradecase
USER app
EXPOSE 8000
CMD ["python", "-m", "tradecase.platform.server"]
