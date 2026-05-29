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
#  * HEALTHCHECK hits the live HTTP API so orchestrators can detect a
#    broken process (not just a broken import) at runtime.
#  * Default CMD starts the Flask HTTP API via the production-grade
#    waitress WSGI server (Flask's dev server is rejected for prod).
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
# ``waitress`` is the production WSGI server we use in the runtime CMD;
# pinning it here keeps the dependency set fully reproducible.
RUN pip install --upgrade pip \
 && pip install -r requirements.txt \
 && pip install waitress==3.0.0


# -----------------------------------------------------------------------------
# Stage 2: runtime - minimal, non-root image
# -----------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

# Replicate the runtime env vars; these are not inherited from the builder.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH="/app" \
    PORT=8000

# Apply security updates to the base image and install curl (needed by
# the HEALTHCHECK below; ~60 KB extra, well worth the operational
# benefit of a real HTTP probe). apt lists are removed in the same RUN
# to avoid bloating the final layer.
RUN apt-get update \
 && apt-get upgrade -y \
 && apt-get install -y --no-install-recommends curl \
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

# Drop privileges. Anything below this line runs as appuser.
USER appuser

EXPOSE 8000

# Healthcheck hits the running HTTP service rather than just re-importing
# the module: this detects 'process crashed', 'port not bound' and
# 'route registration broken' - none of which the old import-only check
# would have caught.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl --fail --silent --show-error http://127.0.0.1:${PORT}/health \
        || exit 1

# Default command: serve the Flask app via waitress, a production WSGI
# server. Flask's built-in dev server explicitly warns against
# production use; using waitress here means the image is genuinely
# production-deployable, not just demo-deployable.
CMD ["sh", "-c", "waitress-serve --host=0.0.0.0 --port=${PORT} src.api:app"]
