"""
Tests for the Flask HTTP API.

We use Flask's built-in ``test_client`` rather than spinning up a real
server: it exercises the full WSGI request/response cycle in-process,
so the assertions are realistic without the test suite needing a port.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import pytest

from src.api import API_VERSION, create_app


@pytest.fixture
def client():
    """A fresh test client per test - no shared state between cases."""
    app = create_app({"TESTING": True})
    return app.test_client()


@pytest.fixture
def valid_profile() -> Dict[str, Any]:
    return {
        "skin_type": "oily",
        "age": 25,
        "concerns": ["acne"],
        "climate": "humid",
        "budget": "medium",
        "routine_preference": "balanced",
        "sensitivities": [],
    }


class TestHealthEndpoint:
    """``/health`` is the contract Docker's HEALTHCHECK relies on."""

    def test_returns_200_with_status_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        body = response.get_json()
        # Document the contract explicitly: orchestrators rely on it.
        assert body["status"] == "ok"
        assert body["service"] == "skincare-classifier"


class TestVersionEndpoint:
    def test_returns_api_version(self, client):
        response = client.get("/version")
        assert response.status_code == 200
        body = response.get_json()
        assert body["version"] == API_VERSION
        # When the pipeline doesn't inject GIT_COMMIT or APP_ENV, the API
        # must still respond — 'unknown' is a stable sentinel for parsers.
        assert "git_commit" in body
        assert "environment" in body

    def test_environment_field_reflects_app_env_variable(self):
        """APP_ENV is injected by simulateDeploy (-e APP_ENV=dev/test/staging/prod).

        The /version endpoint must surface it so that an operator can
        confirm which environment a running container was promoted to
        without having to inspect docker inspect or the orchestrator.
        """
        import os
        os.environ["APP_ENV"] = "staging"
        try:
            # Create a fresh app so the env var is read at request time,
            # not at import time (os.environ is global state).
            app = create_app({"TESTING": True})
            response = app.test_client().get("/version")
            body = response.get_json()
            assert body["environment"] == "staging"
        finally:
            # Always restore the process environment so other tests
            # running in the same process are unaffected.
            del os.environ["APP_ENV"]


class TestRecommendEndpoint:
    def test_returns_routine_for_valid_profile(self, client, valid_profile):
        response = client.post("/recommend", json=valid_profile)
        assert response.status_code == 200
        body = response.get_json()
        # We do not duplicate the component-level assertions here;
        # the API only owns the wire contract.
        assert "morning_routine" in body
        assert "evening_routine" in body

    def test_returns_routine_without_optional_sensitivities_key(
        self, client
    ):
        """``sensitivities`` is optional in the component; the API must
        accept a profile that omits it entirely (not just an empty list).

        This proves the wire contract: callers that don't know about
        sensitivities still get a valid 200 response, not a 400 for a
        missing field.
        """
        profile_without_sensitivities = {
            "skin_type": "oily",
            "age": 25,
            "concerns": ["acne"],
            "climate": "humid",
            "budget": "medium",
            "routine_preference": "balanced",
            # 'sensitivities' deliberately omitted
        }
        response = client.post("/recommend", json=profile_without_sensitivities)
        assert response.status_code == 200
        body = response.get_json()
        assert "morning_routine" in body
        assert "evening_routine" in body

    def test_rejects_non_json_body_with_400(self, client):
        response = client.post(
            "/recommend",
            data="this is not json",
            content_type="text/plain",
        )
        assert response.status_code == 400
        body = response.get_json()
        assert body["error"] == "invalid_json"

    def test_invalid_profile_returns_400_with_structured_error(
        self, client, valid_profile
    ):
        # Trigger the InvalidFieldValueError path.
        valid_profile["skin_type"] = "alien"
        response = client.post("/recommend", json=valid_profile)
        assert response.status_code == 400
        body = response.get_json()
        # Three pieces of contract: error code, message, exception class
        # name. The class name lets API consumers branch on failure
        # modes without parsing free-text messages.
        assert body["error"] == "invalid_profile"
        assert "skin_type" in body["message"]
        assert body["type"] == "InvalidFieldValueError"

    def test_missing_field_returns_specific_exception_type(
        self, client, valid_profile
    ):
        del valid_profile["age"]
        response = client.post("/recommend", json=valid_profile)
        body = response.get_json()
        assert body["type"] == "MissingFieldError"

    def test_minor_with_aging_returns_incompatible_selection(
        self, client, valid_profile
    ):
        valid_profile["age"] = 14
        valid_profile["concerns"] = ["aging"]
        response = client.post("/recommend", json=valid_profile)
        body = response.get_json()
        assert response.status_code == 400
        assert body["type"] == "IncompatibleSelectionError"


class TestUnknownRoutes:
    def test_unknown_route_returns_404(self, client):
        response = client.get("/does-not-exist")
        assert response.status_code == 404


class TestInternalServerError:
    """Verifies the 500 error handler produces a consistent JSON envelope.

    Flask re-raises exceptions in TESTING mode by default, so we must
    explicitly disable PROPAGATE_EXCEPTIONS to allow the error handler
    to fire. This test exercises the defensive handler that guards against
    unexpected bugs in the component layer reaching the HTTP client as an
    unformatted traceback.
    """

    def test_unhandled_exception_returns_500_json(self):
        # PROPAGATE_EXCEPTIONS=False ensures Flask routes unhandled exceptions
        # through the registered @app.errorhandler(500) rather than re-raising.
        app = create_app({
            "TESTING": True,
            "PROPAGATE_EXCEPTIONS": False,
        })
        client = app.test_client()
        valid_profile = {
            "skin_type": "oily", "age": 25, "concerns": ["acne"],
            "climate": "humid", "budget": "medium",
            "routine_preference": "balanced", "sensitivities": [],
        }
        # Patch at the import site inside src.api so Flask's dispatch sees it.
        with patch(
            "src.api.recommend_skincare_routine",
            side_effect=RuntimeError("simulated unexpected failure"),
        ):
            response = client.post("/recommend", json=valid_profile)
        assert response.status_code == 500
        body = response.get_json()
        assert body is not None, "500 response must be JSON, not an HTML traceback"
        assert body["error"] == "internal_error"
        assert "unexpected" in body["message"].lower()


class TestPayloadLimits:
    """The default MAX_CONTENT_LENGTH is a small but real safety control."""

    def test_oversized_payload_is_rejected(self, client):
        # Stuff a huge string into one of the list fields so the body
        # exceeds the configured 256 KiB cap.
        big = {
            "skin_type": "normal",
            "age": 30,
            "concerns": [],
            "climate": "temperate",
            "budget": "medium",
            "routine_preference": "balanced",
            # ~300 KiB string - safely over the limit.
            "sensitivities": ["x" * (300 * 1024)],
        }
        response = client.post("/recommend", json=big)
        # Flask returns 413 for payloads that exceed MAX_CONTENT_LENGTH.
        assert response.status_code == 413
        # The response must be JSON, not Flask's default HTML error page.
        body = response.get_json()
        assert body is not None
        assert body["error"] == "payload_too_large"
