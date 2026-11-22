"""The Ronaldo agent: card shape, both request shapes, and honest refusals."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ronaldo_agent.knowledge import answer
from ronaldo_agent.server import create_app, load_card


def _client() -> TestClient:
    return TestClient(create_app())


# -- card -----------------------------------------------------------------
def test_card_is_valid_and_matches_what_the_orchestrator_needs() -> None:
    from orchestrator.admin.onboarding import validate_card

    card = load_card()
    assert card["name"] == "ronaldo-agent"
    assert card["description"]
    assert len(card["skills"]) >= 2
    for skill in card["skills"]:
        assert skill.get("id") and skill.get("name") and skill.get("description")
    # A card with no problems must pass the same pre-check the onboarding tool runs.
    assert validate_card(card, card["url"]) == []


def test_card_url_can_be_overridden_for_docker(monkeypatch) -> None:
    monkeypatch.setenv("RONALDO_AGENT_URL", "http://host.docker.internal:9103")
    card = load_card()
    assert card["url"] == "http://host.docker.internal:9103"
    assert card["provider"]["url"] == card["url"]


def test_card_is_served_at_the_well_known_path() -> None:
    response = _client().get("/.well-known/agent-card.json")
    assert response.status_code == 200
    assert response.json()["name"] == "ronaldo-agent"


def test_card_also_served_at_legacy_path() -> None:
    assert _client().get("/.well-known/agent.json").status_code == 200


# -- answers --------------------------------------------------------------
def test_identity_question() -> None:
    assert "Portuguese professional footballer" in answer("who is ronaldo?")


def test_birth_question() -> None:
    text = answer("when and where was cristiano ronaldo born?")
    assert "5 February 1985" in text
    assert "Funchal" in text


def test_biography_question_returns_the_full_life_story() -> None:
    text = answer("who is ronaldo and what is his biography?")
    assert text.startswith("Cristiano Ronaldo — biography")
    # birth, clubs, records and personal life must all be present
    assert "5 February 1985" in text
    assert "Sporting CP" in text and "Al Nassr" in text
    assert "Ballon d'Or" in text
    assert "Georgina Rodriguez" in text


def test_birthday_question_does_not_trigger_full_biography() -> None:
    text = answer("when is ronaldo's birthday?")
    assert not text.startswith("Cristiano Ronaldo — biography")
    assert "5 February 1985" in text


def test_clubs_question() -> None:
    text = answer("which clubs has he played for?")
    assert "Sporting CP" in text and "Real Madrid" in text and "Al Nassr" in text


def test_records_question() -> None:
    text = answer("what records does he hold?")
    assert "all-time" in text.lower()


def test_out_of_scope_question_is_refused_not_guessed() -> None:
    text = answer("what is the capital of France?")
    assert "only answer questions about Cristiano Ronaldo" in text


def test_empty_question_asks_for_a_topic() -> None:
    assert "Ask me about" in answer("   ")


# -- protocols ------------------------------------------------------------
def test_jsonrpc_message_send() -> None:
    response = _client().post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": "m1",
                    "role": "user",
                    "parts": [{"kind": "text", "text": "who is ronaldo?"}],
                }
            },
        },
    )
    body = response.json()
    assert response.status_code == 200
    assert body["jsonrpc"] == "2.0"
    assert body["result"]["parts"][0]["kind"] == "text"
    assert "footballer" in body["result"]["parts"][0]["text"]


def test_litellm_simple_shape() -> None:
    response = _client().post(
        "/", json={"message": {"role": "user", "parts": [{"type": "text", "text": "his records?"}]}}
    )
    assert response.status_code == 200
    assert "all-time" in response.json()["result"]["parts"][0]["text"]


def test_unknown_jsonrpc_method_is_an_error_not_a_crash() -> None:
    response = _client().post("/", json={"jsonrpc": "2.0", "id": "9", "method": "tasks/get"})
    assert response.json()["error"]["code"] == -32601


def test_health() -> None:
    assert _client().get("/health").json()["status"] == "ok"
