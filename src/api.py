"""
HTTP API wrapping the Skincare Routine Classifier.

A deliberately small Flask app that exposes the pure component as a
network service. Three endpoints, three concerns:

* ``POST /recommend`` - the actual business endpoint
* ``GET  /health``    - liveness probe consumed by Docker / Jenkins
* ``GET  /version``   - simple build-traceability stamp

Design notes
------------
* Routing and parsing only - all business rules stay in
  ``src/component.py``. This keeps the API layer trivially testable and
  the unit tests of the component layer unaffected.
* Validation errors return ``400`` with a JSON body rather than the
  default Flask HTML traceback - safer and more useful to API consumers.
* The app is constructed via a factory (``create_app``) so each test
  gets its own isolated ``app.test_client()`` without leaking global
  state between cases.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Tuple

from flask import Flask, Response, jsonify, request

from src.component import (
    InvalidProfileError,
    recommend_skincare_routine,
)


# Bumped manually with each meaningful release. Kept here (not in a
# generated file) so it shows up in code review and ships with the image.
API_VERSION: str = "1.0.0"


def create_app(config: Mapping[str, Any] | None = None) -> Flask:
    """Application factory.

    Using a factory (vs a module-level ``app = Flask(__name__)``) means:
    * Tests can spin up isolated app instances per test.
    * The container CMD passes a dedicated config in (e.g. ``TESTING``)
      without monkey-patching globals.
    """
    app = Flask(__name__)

    # Sensible defaults; overridable per environment via ``config``.
    app.config.update(
        # 256 KiB request cap - JSON profiles are < 1 KiB in practice, so
        # this is generous while still bounding the attack surface.
        MAX_CONTENT_LENGTH=256 * 1024,
        JSON_SORT_KEYS=False,
    )
    if config:
        app.config.update(dict(config))

    _register_routes(app)
    _register_error_handlers(app)
    return app


def _register_routes(app: Flask) -> None:
    """Attach the three HTTP routes to ``app``."""

    @app.get("/health")
    def health() -> Tuple[Response, int]:
        """Liveness probe.

        Returns a stable, machine-readable JSON document. Docker's
        ``HEALTHCHECK`` and the Jenkins smoke-test stage both hit this
        endpoint to decide whether the image is functional.
        """
        return jsonify({"status": "ok", "service": "skincare-classifier"}), 200

    @app.get("/version")
    def version() -> Tuple[Response, int]:
        """Build-traceability endpoint.

        Surfaces both the application version and (when supplied via the
        environment by the CI pipeline) the git commit SHA - so that an
        operator can correlate a running container with a specific build.
        """
        return jsonify({
            "version": API_VERSION,
            "git_commit": os.environ.get("GIT_COMMIT", "unknown"),
        }), 200

    @app.post("/recommend")
    def recommend() -> Tuple[Response, int]:
        """Generate a skincare routine for the supplied JSON profile.

        Validation failures from the component layer are caught by the
        registered error handler below; only successful responses are
        produced inline here.
        """
        # ``force=True`` accepts any content-type; ``silent=True`` makes
        # Flask return ``None`` on a parse error rather than raising,
        # so we can produce a uniform JSON error envelope.
        payload = request.get_json(force=True, silent=True)
        if payload is None:
            return jsonify({
                "error": "invalid_json",
                "message": "Request body must be valid JSON.",
            }), 400

        result = recommend_skincare_routine(payload)
        return jsonify(result), 200


def _register_error_handlers(app: Flask) -> None:
    """Translate domain exceptions into well-formed HTTP responses.

    Returning JSON 400s instead of Flask's default HTML keeps the API
    consistent and safe to embed in other tooling.
    """

    @app.errorhandler(InvalidProfileError)
    def _on_invalid_profile(exc: InvalidProfileError) -> Tuple[Response, int]:
        return jsonify({
            "error": "invalid_profile",
            "message": str(exc),
            "type": type(exc).__name__,
        }), 400

    @app.errorhandler(413)
    def _on_payload_too_large(exc: Exception) -> Tuple[Response, int]:
        return jsonify({
            "error": "payload_too_large",
            "message": "Request body exceeds the 256 KiB size limit.",
        }), 413

    @app.errorhandler(500)
    def _on_internal_error(exc: Exception) -> Tuple[Response, int]:
        return jsonify({
            "error": "internal_error",
            "message": "An unexpected server error occurred.",
        }), 500


# A module-level ``app`` is convenient for ``flask run`` and for the
# Docker CMD; the factory remains the canonical entry point.
app = create_app()


if __name__ == "__main__":  # pragma: no cover
    # 0.0.0.0 is intentional inside a container; production traffic
    # goes through waitress (see Dockerfile CMD), this fallback exists
    # only for local development.
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=int(os.environ.get("PORT", "8000")))
