# AHIA backend container image.
#
# Design rules:
#   * multi-stage: build tooling and the development toolchain never reach the
#     runtime layer
#   * runtime dependencies come from requirements.prod.lock, the audited
#     runtime-only closure. The test toolchain is not installed in the image.
#   * hashes are enforced at install time; a tampered artifact fails the build
#   * the process runs as a non-root user with no shell home
#   * no secret is baked in. Configuration arrives as environment variables at
#     runtime, and every secret is documented in docs/PREREQUISITES.md.
#
# Build:
#   docker build -t ahia-backend:local backend
# Run:
#   docker run --rm -p 8000:8000 --env-file backend/.env ahia-backend:local

# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: resolve and install dependencies into a virtual environment
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Only the files needed to install. Copying the lock first keeps this layer
# cached when application code changes.
COPY requirements.prod.lock pyproject.toml ./
COPY src ./src

RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --quiet --upgrade pip setuptools wheel \
    && /opt/venv/bin/python -m pip install --quiet --require-hashes --no-deps \
        --requirement requirements.prod.lock \
    && /opt/venv/bin/python -m pip install --quiet --no-deps .

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# A dedicated unprivileged account. The application never needs to write to the
# filesystem, so it does not get a writable home directory.
RUN groupadd --system --gid 1001 ahia \
    && useradd --system --uid 1001 --gid ahia --no-create-home --home-dir /app ahia

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

USER ahia

EXPOSE 8000

# Liveness only. Readiness (which may touch the database) is a separate endpoint
# and must not be used as the container health check, because a dependency
# outage should not cause the orchestrator to kill a healthy process.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,sys,urllib.request; \
port=os.environ.get('PORT','8000'); \
sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=3).status == 200 else 1)"

# Northflank and similar platforms inject PORT. The default keeps local runs
# working without configuration.
CMD ["sh", "-c", "exec uvicorn ahia.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log --proxy-headers"]
