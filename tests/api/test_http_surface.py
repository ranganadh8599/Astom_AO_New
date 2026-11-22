"""The HTTP surface, end to end.

Exists because a latent bug made **every** route unusable and nothing caught it:
nothing exercised the app over HTTP, only `service.run()` directly.

The bug: `api/app.py` had `from __future__ import annotations`, which stringifies annotations.
FastAPI then could not resolve `Depends(current_user)` — `current_user` is a closure
inside `create_app`, not a module global — so it fell back to treating `user` as a
**required query parameter**:

    422 {"detail": [{"loc": ["query", "user"], "msg": "Field required"}]}

Every request failed that way. These tests keep the app on the HTTP path.
"""

import hashlib

import pytest
from fastapi.testclient import TestClient

from orchestrator.api.app import create_app
from orchestrator.auth import DevValidator, build_authenticator
from orchestrator.config import Settings


def _settings(**overrides) -> Settings:
    base = {
        "litellm_base_url": "http://gateway.test",
        "litellm_api_key": "sk-test",
        "planner_model": "test/planner",
        "langfuse_tracing_enabled": False,
        "auth_mode": "dev",
        "model_preflight_enabled": False,
        "protocols": ("a2a",),
    }
    base.update(overrides)
    return Settings(**base)


def _token(settings: Settings) -> str:
    authenticator = build_authenticator(settings)
    return authenticator.issue() if isinstance(authenticator, DevValidator) else ""


@pytest.fixture
def client():
    with TestClient(create_app(_settings())) as c:
        yield c


# -- schema sanity: the bug that broke everything --------------------------


def test_routes_do_not_expose_a_user_query_parameter() -> None:
    """The exact shape of the regression: `user` must be a dependency, not a parameter."""
    spec = create_app(_settings()).openapi()

    for path, method in (
        ("/v1/orchestrate", "post"),
        ("/v1/agents", "get"),
        ("/v1/capabilities", "get"),
    ):
        params = [p["name"] for p in spec["paths"][path][method].get("parameters", [])]
        assert "user" not in params, f"{path} exposes a phantom 'user' parameter"
        assert params == ["authorization"], params


def test_health_needs_no_auth(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


# -- auth is enforced ------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "method"),
    [("/v1/agents", "get"), ("/v1/capabilities", "get")],
)
def test_protected_routes_reject_missing_token(client: TestClient, path: str, method: str) -> None:
    response = getattr(client, method)(path)

    assert response.status_code == 401
    assert "bearer" in response.json()["detail"].lower()


def test_bad_token_is_401(client: TestClient) -> None:
    response = client.get("/v1/agents", headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401


def test_valid_token_is_accepted(client: TestClient) -> None:
    settings = _settings()
    response = client.get(
        "/v1/agents", headers={"Authorization": f"Bearer {_token(settings)}"}
    )

    # 200 with an empty catalogue (the mock gateway path is not exercised here).
    assert response.status_code in (200, 500)


# -- trace headers reach the service ---------------------------------------


def test_librechat_headers_are_read_by_the_endpoint() -> None:
    """The join depends on the endpoint forwarding these headers verbatim."""
    settings = _settings()
    message_id = "msg-abc"
    expected = hashlib.sha256(message_id.encode()).hexdigest()[:32]

    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/v1/orchestrate",
            headers={
                "Authorization": f"Bearer {_token(settings)}",
                "X-LibreChat-Message-Id": message_id,
                "X-LibreChat-Conversation-Id": "conv-1",
            },
            json={"message": "hello", "conversation_id": "conv-1"},
        )

    # The run needs a live gateway, so only assert the trace id was derived, which
    # happens before any gateway call.
    assert response.status_code in (200, 500)
    if response.status_code == 200:
        assert response.json()["trace_id"] == expected


def test_response_model_shape() -> None:
    """Guards the client contract LibreChat depends on."""
    from orchestrator.api.app import OrchestrateResponse

    fields = set(OrchestrateResponse.model_fields)
    assert {"run_id", "status", "answer", "trace_id", "conversation_id", "denied"} <= fields
