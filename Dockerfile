# Production builds pass digest-qualified bases; the development Compose may use tags.
ARG PYTHON_IMAGE=python:3.12-slim
ARG DOCKER_CLI_IMAGE=docker:27-cli
FROM ${DOCKER_CLI_IMAGE} AS docker-cli
FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 HOME=/tmp XDG_CACHE_HOME=/tmp/cache
WORKDIR /app
# Existing pinned-source preparation endpoints use git, never a Provider CLI.
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY ops/container/healthcheck.py /app/healthcheck.py
RUN pip install --no-cache-dir . \
    && mkdir -p /workspace && chown 999:999 /workspace
USER 999:999

FROM base AS api
EXPOSE 8000
CMD ["uvicorn", "hypertest.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS worker
USER root
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
USER 999:999
CMD ["python", "-m", "hypertest.worker"]

# Keep the existing developer `docker compose build api` default safe.
FROM api AS production
