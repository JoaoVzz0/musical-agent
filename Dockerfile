FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS base
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN useradd --create-home --uid 1000 app

FROM base AS app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
COPY data ./data
RUN uv sync --locked --no-dev && mkdir -p var && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["adk", "web", "--host", "0.0.0.0", "--port", "8000", "src"]

FROM base AS test
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-install-project
COPY . .
RUN uv sync --locked && git init -q && mkdir -p var && chown -R app:app /app
USER app
CMD ["pytest"]
