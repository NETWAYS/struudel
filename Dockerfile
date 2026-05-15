# syntax=docker/dockerfile:1.7

# =============================================================================
# Stage 1: Compile Tailwind CSS + daisyUI bundle
# =============================================================================
FROM debian:12-slim AS css-builder

ARG TAILWIND_VERSION=v4.1.18

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && ARCH=$(uname -m) \
    && if [ "$ARCH" = "aarch64" ]; then TW_ARCH="linux-arm64"; else TW_ARCH="linux-x64"; fi \
    && curl -fsSLo /usr/local/bin/tailwindcss \
       "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-${TW_ARCH}" \
    && chmod +x /usr/local/bin/tailwindcss

WORKDIR /build

COPY css ./css
COPY src ./src

RUN tailwindcss \
        -i /build/css/input.css \
        -o /build/src/struudel/static/css/app.css \
        --minify

# =============================================================================
# Stage 2: Runtime image
# =============================================================================
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_CACHE_DIR=/app/.cache/uv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    FLASK_APP=struudel.app:create_app

# git is needed by hatch-vcs during `uv sync` to derive the package version
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 struudel \
    && useradd --system --uid 1000 --gid struudel --home-dir /app --shell /usr/sbin/nologin struudel

WORKDIR /app

COPY pyproject.toml alembic.ini ./
COPY css ./css
COPY src ./src
COPY alembic ./alembic
COPY .git ./.git

RUN --mount=type=cache,target=/app/.cache/uv \
    uv sync --all-groups

COPY --from=css-builder /usr/local/bin/tailwindcss /usr/local/bin/tailwindcss
COPY --from=css-builder /build/src/struudel/static/css/app.css /app/src/struudel/static/css/app.css

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && chown -R struudel:struudel /app

USER struudel

EXPOSE 5009

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["app"]
