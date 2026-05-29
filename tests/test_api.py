"""
Tests for the Flask HTTP API.

We use Flask's built-in ``test_client`` rather than spinning up a real
server: it exercises the full WSGI request/response cycle in-process,
so the assertions are realistic without the test suite needing a port.
"""

from __future__ import annotations

from typing import Any, Dict

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
        # When the pipeline doesn't inject GIT_COMMIT, the API should
        # still respond - 'unknown' is a stable sentinel for parsers.
        assert "git_commit" in body


class TestRecommendEndpoint:
    def test_returns_routine_for_valid_profile(self, client, valid_profile):
        response = client.post("/recommend", json=valid_profile)
        assert response.status_code == 200
        body = response.get_json()
        # We do not duplicate the component-level assertions here;
        # the API only owns the wire contract.
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
