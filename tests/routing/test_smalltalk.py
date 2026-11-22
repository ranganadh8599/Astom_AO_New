"""Small talk: greetings, thanks, and questions about the assistant.

Before this existed, every greeting reached the coverage gate and came back as:

    "Nothing in the registered catalogue covers that request."

Technically correct, and a poor answer to "hi". The pattern is borrowed from
`multi_agent_system` in this workspace, whose router reserves an `ANSWER` route for
"greetings, thanks, and basic acknowledgments" plus "system capabilities and features",
separate from its knowledge route.

The rule that matters most here: **a greeting followed by a question is a question.**
Answering only the greeting would silently drop the question, which is worse than the
original behaviour.
"""

from __future__ import annotations

import pytest

from orchestrator.routing import smalltalk


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("hi", "greeting"),
        ("hello", "greeting"),
        ("Hey!", "greeting"),
        ("good morning", "greeting"),
        ("Hello.", "greeting"),
        ("  hi  ", "greeting"),
        ("thanks", "thanks"),
        ("Thank you!", "thanks"),
        ("thx", "thanks"),
        ("that helps", "thanks"),
        ("got it", "thanks"),
        ("perfect", "thanks"),
        ("what can you do?", "capabilities"),
        ("who are you?", "capabilities"),
        ("what are you?", "capabilities"),
        ("help", "capabilities"),
    ],
)
def test_recognised_smalltalk(text: str, kind: str) -> None:
    result = smalltalk.detect(text)

    assert result is not None, text
    assert result.kind == kind
    assert result.reply


@pytest.mark.parametrize(
    "text",
    [
        # A greeting plus a question must be routed, not answered with a hello.
        "hi, what is our leave policy?",
        "hello - where is the office?",
        "thanks, and what are the open incidents in Lyon?",
        # Real business questions
        "where is our office",
        "who is ronaldo",
        "is PUMP-1042 running",
        "how many leave days do I get",
        # Unrelated chatter that is not a greeting
        "tell me a joke",
        "what is the weather",
    ],
)
def test_not_smalltalk(text: str) -> None:
    assert smalltalk.detect(text) is None, text


def test_question_mark_is_enough_to_keep_routing() -> None:
    """The cheapest correct guard: a question mark means there is a question."""
    assert smalltalk.detect("hi?") is None


def test_overlong_message_is_not_smalltalk() -> None:
    assert smalltalk.detect("hello " * 20) is None


def test_empty_message_is_not_smalltalk() -> None:
    assert smalltalk.detect("") is None
    assert smalltalk.detect("   ") is None


def test_capabilities_reply_can_be_overridden() -> None:
    result = smalltalk.detect("what can you do?", capabilities_reply="Custom help text.")

    assert result is not None
    assert result.reply == "Custom help text."


# -- personalisation -------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Alice", "Alice"),
        ("  Alice  ", "Alice"),
        ("Orch Tester", "Orch"),          # first name only
        ("Bob Smith Jones", "Bob"),
        ("Tester, Orch", "Orch"),         # "Last, First" form
        ("Anne-Marie O'Neill", "Anne-Marie"),
    ],
)
def test_display_name_extracts_a_first_name(raw: str, expected: str) -> None:
    assert smalltalk.display_name(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",                       # nothing supplied
        "alice@contoso.com",      # email is not a name
        "6b00d8662f63e48e5b1a9b26",  # opaque id
        "user-123",               # id with digits
        "A",                      # too short to be a name
        "X" * 50,                 # implausible length
    ],
)
def test_display_name_rejects_non_names(raw: str) -> None:
    """Greeting someone by their user id is worse than a plain "Hello"."""
    assert smalltalk.display_name(raw) == ""


def test_greeting_is_personalised() -> None:
    result = smalltalk.detect("hi", user_name="Alice")

    assert result is not None
    assert result.reply.startswith("Hello Alice.")


def test_thanks_is_personalised() -> None:
    result = smalltalk.detect("thanks, that helps!", user_name="Alice")

    assert result is not None
    assert "Alice" in result.reply


def test_email_name_falls_back_to_neutral_greeting() -> None:
    result = smalltalk.detect("hi", user_name="alice@contoso.com")

    assert result is not None
    assert result.reply.startswith("Hello.")
    assert "alice@" not in result.reply


def test_capabilities_reply_is_not_personalised() -> None:
    """It answers a question about the system, not about the person."""
    result = smalltalk.detect("what can you do?", user_name="Alice")

    assert result is not None
    assert "Alice" not in result.reply


def test_personalisation_does_not_break_routing() -> None:
    """"hi, what is our leave policy?" must still route even with a name available."""
    assert smalltalk.detect("hi, what is our leave policy?", user_name="Alice") is None


# -- a request is never smalltalk, whatever a model says -------------------


@pytest.mark.parametrize(
    "text",
    [
        "write me a short poem about winter",
        "translate good morning into Japanese",
        "summarise this paragraph for me",
        "calculate 12% of 90",
        "list the open incidents",
        "show me the stock level for SKU-4471",
        "how many annual leave days do I get?",
        "explain exactly how a heat pump works",
    ],
)
def test_a_content_request_is_not_smalltalk(text: str) -> None:
    assert smalltalk.looks_like_request(text), text
    assert smalltalk.detect(text) is None, text


@pytest.mark.parametrize("text", ["hi", "thanks, that helps", "good morning", "got it"])
def test_social_messages_are_not_requests(text: str) -> None:
    assert not smalltalk.looks_like_request(text), text


@pytest.mark.parametrize("text", ["what can you do?", "who are you?", "help"])
def test_questions_about_the_assistant_are_not_requests(text: str) -> None:
    """They end in "?" but must keep their smalltalk outcome, not become a decline."""
    assert not smalltalk.looks_like_request(text), text


def test_neutral_reply_personalises_only_with_a_usable_name() -> None:
    assert smalltalk.neutral_reply(user_name="Alice").reply.startswith("Hello Alice.")
    assert smalltalk.neutral_reply(user_name="alice@contoso.com").reply.startswith("Hello.")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("hi, what is our leave policy?", "what is our leave policy?"),
        ("good morning team, any incidents open?", "team, any incidents open?"),
        ("hello, please summarise the open tickets", "please summarise the open tickets"),
        # A greeting with nothing actionable after it is the whole message.
        ("good day to you all", "good day to you all"),
        ("hey there", "hey there"),
        ("hi", "hi"),
    ],
)
def test_leading_greeting_is_stripped_only_when_a_request_follows(
    text: str, expected: str
) -> None:
    assert smalltalk.strip_leading_greeting(text) == expected


async def test_a_gate_smalltalk_verdict_is_answered_directly() -> None:
    """The gate's contract says the orchestrator answers smalltalk itself; keep it."""
    import json

    from orchestrator.auth import UserContext
    from orchestrator.gateway import LiteLLMGateway
    from orchestrator.service import OrchestratorService
    from tests.conftest import FakeGateway, make_settings

    fake = FakeGateway()
    fake.gate_raw = json.dumps(
        {"intent": "smalltalk", "can_answer": False, "targets": [],
         "reason": "social message", "confidence": 0.9}
    )
    settings = make_settings()
    service = OrchestratorService(settings, gateway=LiteLLMGateway(settings, client=fake.client()))
    async with service:
        result = await service.run("good day to you all", UserContext(oid="u", name="U", roles=()))

    assert result.status == "completed" and result.tasks == []
    assert result.answer.startswith("Hello.")
    assert any("smalltalk (gate)" in note for note in result.notes)


async def test_a_mislabelled_request_is_declined_not_greeted() -> None:
    """"write me a poem" mislabelled as smalltalk must not produce a greeting."""
    import json

    from orchestrator.auth import UserContext
    from orchestrator.gateway import LiteLLMGateway
    from orchestrator.service import OrchestratorService
    from tests.conftest import FakeGateway, make_settings

    fake = FakeGateway()
    fake.gate_raw = json.dumps(
        {"intent": "smalltalk", "can_answer": False, "targets": [],
         "reason": "thought it was social", "confidence": 0.4}
    )
    settings = make_settings()
    service = OrchestratorService(settings, gateway=LiteLLMGateway(settings, client=fake.client()))
    async with service:
        result = await service.run(
            "write me a short poem about winter", UserContext(oid="u", name="U", roles=())
        )

    assert result.status == "completed" and result.tasks == []
    assert "Nothing in the registered catalogue" in result.answer
    assert not result.answer.startswith("Hello")
    assert "greeting" not in result.answer.lower()


# -- integration with the graph -------------------------------------------


async def test_greeting_is_answered_without_calling_a_target() -> None:
    """No gateway call, no planner, no gate — a greeting is free."""
    import httpx

    from orchestrator.auth import UserContext
    from orchestrator.config import Settings
    from orchestrator.gateway import LiteLLMGateway
    from orchestrator.service import OrchestratorService

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        # Discovery still runs before `check_coverage`; an empty registry is enough here.
        if request.url.path == "/v1/agents":
            return httpx.Response(200, json=[])
        if request.url.path == "/v1/mcp/server":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, json={})

    settings = Settings(
        litellm_base_url="http://gateway.test",
        litellm_api_key="sk-test",
        planner_model="test/planner",
        langfuse_tracing_enabled=False,
        protocols=("a2a",),
    )
    gateway = LiteLLMGateway(
        settings,
        client=httpx.AsyncClient(
            base_url="http://gateway.test", transport=httpx.MockTransport(handler)
        ),
    )
    service = OrchestratorService(settings, gateway=gateway)
    async with service:
        result = await service.run("hi", UserContext(oid="u", name="U", roles=()))

    assert result.status == "completed"
    assert result.tasks == []
    assert "route" in result.answer.lower() or "hello" in result.answer.lower()
    # Discovery runs before `check_coverage` (cheap, cached), so listing calls are expected.
    # What must NOT happen is a model call or an agent invocation.
    assert not [c for c in calls if c in ("/v1/chat/completions",) or c.startswith("/a2a/")], (
        f"a greeting should cost no model call and no agent call, saw {calls}"
    )
