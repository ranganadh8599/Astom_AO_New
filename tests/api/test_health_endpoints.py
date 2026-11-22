"""Route-level contract for /health and /ready.

The unit tests pin `ModelCheck` semantics; these pin what the HTTP endpoints actually
return, since that is what a Kubernetes probe consumes.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from orchestrator.api.app import create_app
from orchestrator.config import Settings
from orchestrator.gateway import LiteLLMGateway


def _settings(**overrides) -> Settings:
    base = {
        "litellm_base_url": "http://gateway.test",
        "litellm_api_key": "sk-test",
        "planner_model": "openai/gpt-4o-mini",
        "langfuse_tracing_enabled": False,
        "protocols": ("a2a",),
        "model_preflight_enabled": False,
    }
    base.update(overrides)
    return Settings(**base)


def _client(handler=None) -> TestClient:
    app = create_app(_settings())
    return TestClient(app)


async def _set_check(app, check) -> None:
    app.state.service._model_check = check


def test_health_is_200_while_pending() -> None:
    with TestClient(create_app(_settings())) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200


def test_health_exposes_the_models_block() -> None:
    with TestClient(create_app(_settings())) as client:
        body = client.get("/health").json()

    assert body["status"] == "ok"
    assert "models" in body
    assert body["models"]["status"] in ("pending", "ok", "degraded", "failed")


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("pending", 200),
        ("ok", 200),
        ("degraded", 200),   # gateway unreachable: stay in rotation
        ("failed", 503),     # rejected model: take traffic away, keep the pod alive
    ],
)
def test_ready_status_code_matrix(status: str, expected: int) -> None:
    from orchestrator.service import ModelCheck

    with TestClient(create_app(_settings())) as client:
        client.app.state.service._model_check = ModelCheck(status=status)

        response = client.get("/ready")

        assert response.status_code == expected
        assert response.json()["models"]["status"] == status


def test_health_stays_200_when_ready_is_503() -> None:
    """The distinction that prevents a crash loop on a misconfiguration."""
    from orchestrator.service import ModelCheck

    with TestClient(create_app(_settings())) as client:
        client.app.state.service._model_check = ModelCheck(
            status="failed", error="gateway rejected model 'x'"
        )

        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
        assert "rejected" in client.get("/ready").json()["models"]["error"]
