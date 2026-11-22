"""Model targets: a LiteLLM model exposed as a routable target.

Until now the orchestrator could only route to A2A agents and MCP tools. A LibreChat
agent exposed through the gateway as a *model* (MAI) could be called but never chosen.

Design decisions this pins:

1. **Allowlisted, not discovered.** `/v1/models` lists hundreds of models; auto-including
   them would fill a planner prompt with noise. Only `MODEL_TARGETS` entries become
   targets. Entries are `model|description`, `;`-separated, because descriptions
   contain commas.
2. **Refusals are failures, not answers.** An LLM asked outside its remit replies
   confidently ("Beyond scope"), which reads as a considered answer. Detecting that and
   marking the result failed lets merge report it honestly.
3. **A malformed entry still becomes a target.** A missing description yields a generic
   one, because a silently dropped target is worse than a vague one.
"""

from __future__ import annotations

import json

import pytest

from orchestrator.config import Settings
from orchestrator.gateway.models import Target


def _settings(**overrides) -> Settings:
    base = {
        "litellm_base_url": "http://gateway.test",
        "litellm_api_key": "sk-test",
        "planner_model": "test/planner",
        "langfuse_tracing_enabled": False,
        "protocols": ("a2a",),
    }
    base.update(overrides)
    return Settings(**base)


# -- parsing MODEL_TARGETS -------------------------------------------------


def test_entry_with_description_is_parsed() -> None:
    parsed = _settings(model_targets=("mai|Alstom company facts",)).model_target_descriptions

    assert parsed == {"mai": "Alstom company facts"}


def test_entry_without_description_gets_a_generic_one() -> None:
    """Dropping it silently would hide a target the operator asked for."""
    parsed = _settings(model_targets=("mai",)).model_target_descriptions

    assert "mai" in parsed
    assert "gateway" in parsed["mai"]


def test_multiple_entries_are_parsed() -> None:
    parsed = _settings(model_targets=("mai|company facts", "helper|hr helper")).model_target_descriptions
    assert parsed == {"mai": "company facts", "helper": "hr helper"}


def test_empty_by_default() -> None:
    """No model is routable unless someone says so."""
    assert _settings().model_target_descriptions == {}


def test_description_may_contain_commas_and_colons() -> None:
    parsed = _settings(model_targets=("mai|facts: name=a, office=b",)).model_target_descriptions
    assert parsed["mai"] == "facts: name=a, office=b"


# -- record shape ----------------------------------------------------------


def test_model_record_shape() -> None:
    record = Target.from_model("mai", description="Alstom company facts")

    assert record.protocol == "model"
    assert record.is_model
    assert not record.is_mcp
    assert record.agent_id == "model:mai"
    assert record.agent_name == "mai"


def test_model_summary_names_the_protocol_and_description() -> None:
    summary = Target.from_model("mai", description="Alstom company facts").summary()

    assert "[model]" in summary
    assert "Alstom company facts" in summary
    # No MCP argument list, no A2A skills list.
    assert "arguments:" not in summary


# -- refusal detection -----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Beyond scope",
        "Beyond scope.",
        "I don't cover that topic.",
        "I do not have information about leave days.",
        "That is outside my scope.",
        # Paraphrases that defeated pure substring matching
        "I do not have the specific address for the Lyon office.",
        "I'm unable to provide that.",
        "We don't cover weather information.",
        "I cannot share that detail.",
        "I am not able to find it.",
        "No information about that topic is available.",
    ],
)
def test_refusals_are_detected(text: str) -> None:
    record = Target.from_model("mai")
    markers = _settings().refusal_markers

    assert record.declined(text, markers) is True


@pytest.mark.parametrize(
    "text",
    [
        "The company name is Alstom and the office is ITC Green Park.",
        "The best season to visit is spring.",
        "Our AI application is called m-ai.",
        # Contains "do not" / "should not" but is a real answer — must not be flagged
        "Do not exceed 40 working hours per week.",
        "You should not have any trouble finding it.",
    ],
)
def test_real_answers_are_not_refusals(text: str) -> None:
    record = Target.from_model("mai")

    assert record.declined(text, _settings().refusal_markers) is False


def test_refusal_matching_is_case_insensitive() -> None:
    record = Target.from_model("mai")

    assert record.declined("BEYOND SCOPE", ("beyond scope",)) is True


def test_empty_markers_disable_detection() -> None:
    record = Target.from_model("mai")

    assert record.declined("Beyond scope", ()) is False


# -- invocation through the gateway ---------------------------------------


async def test_model_target_is_invoked_via_chat_completions() -> None:
    """The whole point: routers can call it, and refusals become failures."""
    import httpx

    from orchestrator.gateway import LiteLLMGateway
    from orchestrator.observability.trace_context import Lineage, TraceContext

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/chat/completions":
            body = json.loads(request.content or b"{}")
            seen.append(body.get("model", ""))
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "The company name is Alstom."}}]}
            )
        return httpx.Response(404, json={"error": "unhandled"})

    settings = _settings()
    client = httpx.AsyncClient(
        base_url="http://gateway.test", transport=httpx.MockTransport(handler)
    )
    gateway = LiteLLMGateway(settings, client=client)

    result = await gateway.invoke(
        Target.from_model("mai", description="company facts"),
        "What is the company name?",
        trace=TraceContext.root(),
        lineage=Lineage.root(),
    )

    assert result.ok is True
    assert result.protocol == "model"
    assert "Alstom" in result.text
    assert seen == ["mai"], "must call the model by name via chat/completions"


async def test_model_refusal_is_reported_as_failure() -> None:
    import httpx

    from orchestrator.gateway import LiteLLMGateway
    from orchestrator.observability.trace_context import Lineage, TraceContext

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "Beyond scope"}}]}
        )

    settings = _settings()
    client = httpx.AsyncClient(
        base_url="http://gateway.test", transport=httpx.MockTransport(handler)
    )
    gateway = LiteLLMGateway(settings, client=client)

    result = await gateway.invoke(
        Target.from_model("mai"),
        "how many leave days?",
        trace=TraceContext.root(),
        lineage=Lineage.root(),
    )

    assert result.ok is False
    assert "declined" in result.error
    assert "Beyond scope" in result.error
