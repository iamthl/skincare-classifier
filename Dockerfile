# syntax=docker/dockerfile:1.7
# =============================================================================
# Production-ready Dockerfile for the Skincare Routine Classifier.
#
# Design highlights
# -----------------
#  * Multi-stage build: dependencies are compiled in a "builder" stage and
#    only the resolved site-packages are copied into the final image, which
#    keeps the runtime image small and free of build toolchains.
#  * Pinned base image digest-equivalent tag (python:3.11-slim-bookworm)
#    plus an explicit OS update for reproducibility and CVE patching.
#  * Non-root user ("appuser") - the container does not run as root, which
#    is one of the highest-impact container hardening practices.
#  * No interactive shells, no apt cache, no .pyc clutter.
#  * HEALTHCHECK so orchestrators can detect a broken image at runtime.
#  * Clear, minimal entrypoint that prints a sample routine - this proves
#    the image is functional in CI smoke tests.
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: builder - install Python deps into an isolated virtualenv
# -----------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS builder

# Standard Python container hygiene:
#  * PYTHONDONTWRITEBYTECODE=1 - no stray .pyc files in the image.
#  * PYTHONUNBUFFERED=1        - logs stream immediately (good for Jenkins).
#  * PIP_NO_CACHE_DIR=1        - smaller image, no stale wheels cached.
#  * PIP_DISABLE_PIP_VERSION_CHECK=1 - no noisy upgrade warnings in CI.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Install build deps only if a requirement needs to compile from source.
# Keeping this in the builder stage means none of it leaks into the final image.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

# Create an isolated virtualenv so we can copy a single directory across
# stages without disturbing the base image's site-packages.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Copy only the requirements first so Docker can cache the layer when the
# application code (but not the dependency list) changes.
COPY requirements.txt ./
RUN pip install --upgrade pip \
 && pip install -r requirements.txt


# -----------------------------------------------------------------------------
# Stage 2: runtime - minimal, non-root image
# -----------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

# Replicate the runtime env vars; these are not inherited from the builder.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH="/app"

# Apply security updates to the base image. apt lists are removed in the
# same RUN to avoid bloating the final layer.
RUN apt-get update \
 && apt-get upgrade -y \
 && rm -rf /var/lib/apt/lists/*

# Create a non-root user and group. Running as root inside a container is a
# significant security smell; this is one of the cheapest mitigations.
RUN groupadd --system --gid 1001 appgroup \
 && useradd  --system --uid 1001 --gid appgroup --shell /usr/sbin/nologin \
             --home-dir /app appuser

# Bring across the virtualenv built in stage 1.
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Copy source last so application changes don't invalidate the deps layer.
# Ownership is set in a single COPY for efficiency.
COPY --chown=appuser:appgroup src/ ./src/
COPY --chown=appuser:appgroup tests/ ./tests/

# Drop privileges. Anything below this line runs as appuser.
USER appuser

# Healthcheck: a successful import proves the package + venv are wired up.
# Orchestrators (k8s, ECS, Docker Swarm) will surface failures here as
# unhealthy containers instead of silently broken ones.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import src.component" || exit 1

# Default command prints a small, deterministic demo routine so that the CI
# pipeline can smoke-test the image with a simple `docker run`.
CMD ["python", "-c", "from src.component import recommend_skincare_routine; \
import json; \
print(json.dumps(recommend_skincare_routine({\
'skin_type':'combination','age':27,'concerns':['acne','dullness'],\
'climate':'temperate','budget':'medium','routine_preference':'balanced',\
'sensitivities':[]}), indent=2))"]
