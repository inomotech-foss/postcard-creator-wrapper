FROM ghcr.io/astral-sh/uv:python3.13-alpine AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0

WORKDIR /app
COPY pyproject.toml uv.lock /app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev --group server

COPY README.md /app/
COPY src /app/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --group server

FROM python:3.13-alpine

COPY --from=builder --chown=app:app /app /app

EXPOSE 8000

ENV PATH="/app/.venv/bin:$PATH"
CMD [ "fastapi", "run", "/app/src/postcard_creator_server" ]
