# syntax=docker/dockerfile:1
#
# Orchestrator image.
#
# Two stages: wheels are built with a compiler available, then installed into a slim
# runtime that has none. The result runs as non-root and starts through
# `python -m orchestrator` — the entry point that supplies a SelectorEventLoop, which
# psycopg requires for async connections. (On Linux that is the default loop, so the
# wrapper is a no-op there; using it anyway keeps one documented command for every
# platform.)
#
# Build:
#   docker build -f deploy/Dockerfile -t a2a-orchestrator:0.1.0 .
# Run (see docker-compose.yml for the full stack):
#   docker run --rm -p 8000:8000 \
#     -e LITELLM_BASE_URL=http://host.docker.internal:4001 \
#     -e LITELLM_API_KEY=sk-... \
#     -e PLANNER_MODEL=openai/gpt-4o-mini \
#     -e AUTH_MODE=shared_key -e ORCH_SHARED_KEY=... \
#     -e CHECKPOINT_BACKEND=postgres \
#     -e POSTGRES_DSN=postgresql://postgres:admin@db:5432/orchestrator \
#     a2a-orchestrator:0.1.0

ARG PYTHON_VERSION=3.12

# ---- build ----------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# libpq-dev is only needed if a wheel has to be built for psycopg; the [postgres]
# extra pulls psycopg[binary], so gcc/headers are a fallback rather than a requirement.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml ./
COPY src ./src

# Wheels for the orchestrator plus the Postgres checkpointer. `dev` and `mcp-server`
# are deliberately excluded: tests do not ship, and the MCP server is its own image.
RUN python -m pip wheel --wheel-dir /wheels ".[postgres]"

# ---- runtime --------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    # Tracing flushes on shutdown; OTel expects a hostname it can resolve.
    OTEL_SDK_DISABLED=false

# curl is for HEALTHCHECK only. No compilers in this stage.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 --shell /usr/sbin/nologin orchestrator

WORKDIR /app

COPY --from=build /wheels /wheels
# The extra must be requested AT INSTALL TIME. Building the wheels with [postgres] only
# puts them in /wheels; a plain `pip install a2a-orchestrator` would resolve base
# dependencies only and leave psycopg out — the container would then fail to boot with
# `CHECKPOINT_BACKEND=postgres` ("needs the optional extra"). Verified by inspecting the
# image, not by assuming.
RUN python -m pip install --no-index --find-links=/wheels "a2a-orchestrator[postgres]" \
 && rm -rf /wheels

# Source is copied as well as installed: the package is on PYTHONPATH, so a config-only
# change can be mounted over /app/src without rebuilding.
COPY --chown=orchestrator:orchestrator src ./src
COPY --chown=orchestrator:orchestrator .env.example ./

USER orchestrator

EXPOSE 8000

# Readiness, not liveness: /ready is what knows whether the checkpointer can reach its
# database. Liveness would restart the container over a DB blip.
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/ready || exit 1

# The wrapper sets loop_factory explicitly. Replace with `--log-level debug` etc. via
# command: in compose; arguments are appended to the module invocation.
ENTRYPOINT ["python", "-m", "orchestrator"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
