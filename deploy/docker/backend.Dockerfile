# AutoSkill API. Built from a context that `deploy/docker/build.sh` assembles: the repository plus
# a `llmswitch/` directory, because the provider library is not on a public index and the server
# cannot reach the machine that holds it.
FROM python:3.12-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /src

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ backend/
COPY packages/ packages/
COPY llmswitch/ llmswitch/

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip wheel \
    && /opt/venv/bin/pip install ./backend ./llmswitch \
    # The wheel the server hands to agents at /dl/autoskill-local/latest.
    && /opt/venv/bin/pip wheel --no-deps -w /opt/dist ./packages/autoskill-local


FROM python:3.12-slim

# git is not a convenience: skills are distributed as read-only repositories under /git.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --create-home --uid 10001 autoskill

COPY --from=build /opt/venv /opt/venv
COPY --from=build /opt/dist /opt/dist
COPY backend/alembic.ini /app/alembic.ini
COPY backend/alembic /app/alembic

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    AUTOSKILL_DATA_DIR=/data \
    AUTOSKILL_LOCAL_DIST_DIR=/opt/dist \
    AUTOSKILL_LLMSWITCH_REGISTRY=/data/llm_providers.json \
    # No GPU and no LM Studio in a container: never try to load a model on our own initiative.
    AUTOSKILL_LLMSWITCH_LOAD_MODELS=0

WORKDIR /app
RUN mkdir -p /data && chown -R autoskill:autoskill /data /app
USER autoskill
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1

CMD ["uvicorn", "autoskill.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
