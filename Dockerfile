FROM ghcr.io/astral-sh/uv:0.12.3 AS uv

FROM python:3.13-slim

ARG RELEASE=local

ENV PATH="/app/.venv/bin:$PATH" \
    RELEASE="$RELEASE" \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./

RUN uv sync --locked --no-default-groups

LABEL org.opencontainers.image.source="https://github.com/alexgoodman53/community_bot"

USER 65532:65532

CMD ["community-worker"]
