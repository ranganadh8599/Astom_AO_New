"""Query building: follow-ups become standalone, several questions become several queries.

The model call is only made when the message looks like it needs one, and every failure
mode returns the original message so retrieval is never worse than without this step.
"""

from __future__ import annotations

import json

import pytest

from orchestrator.gateway import LiteLLMGateway
from orchestrator.observability.trace_context import Lineage, TraceContext
from orchestrator.routing.query_builder import (
    QueryBuilder,
    needs_rewrite,
    parse_queries,
)
from tests.conftest import FakeGateway, make_settings


def _builder(fake: FakeGateway, max_queries: int = 3) -> QueryBuilder:
    settings = make_settings()
    gateway = LiteLLMGateway(settings, client=fake.client())
    return QueryBuilder(gateway, "test/planner", max_queries=max_queries)


async def _build(fake: FakeGateway, message: str, history: str = ""):
    return await _builder(fake).build(
        message, history=history, trace=TraceContext.root(), lineage=Lineage.root()
    )


# -- when is the model worth calling ----------------------------------------


@pytest.mark.parametrize(
    "message, has_history, expected",
    [
        ("How many Ballon d'Ors did Ronaldo win?", False, False),
        ("And in 2016?", True, True),  # short + prior turns = follow-up
        ("And in 2016?", False, False),  # nothing to resolve it against
        ("What is his record? What about incidents at the Pune site?", False, True),
        ("first question\nsecond question", False, True),
        (
            "Tell me about the leave policy for contractors and also check the status of my "
            "expense claim for the November trip",
            False,
            True,
        ),
        (
            "Please explain in detail how the annual leave carry over policy works for "
            "permanent employees in the India offices during the financial year",
            False,
            False,  # long, but a single ask
        ),
        # A reference token is always worth rewriting: the gateway's embedding search
        # returned nothing at all for "what were E-1042's deductions?" and ranks the
        # right tool first for "E-1042 payroll deductions".
        ("is BA2490 delayed?", False, True),
        ("any rooms free on 2026-12-03?", False, True),
        ("what were E-1042's deductions?", False, True),
        ("how many SKU-4471 do we have?", False, True),
        ("how do I check chain wear?", False, False),
    ],
)
def test_needs_rewrite(message: str, has_history: bool, expected: bool) -> None:
    assert needs_rewrite(message, has_history=has_history) is expected


# -- parsing ----------------------------------------------------------------


def test_parse_queries_accepts_plain_fenced_and_wrapped_json() -> None:
    body = '{"queries": ["a b", "c d"]}'
    assert parse_queries(body, 3) == ("a b", "c d")
    assert parse_queries(f"```json\n{body}\n```", 3) == ("a b", "c d")
    assert parse_queries(f"Here you go: {body}", 3) == ("a b", "c d")


def test_parse_queries_dedupes_caps_and_drops_junk() -> None:
    raw = json.dumps({"queries": ["Same", "same", 5, "", "  other  ", "third", "fourth"]})
    assert parse_queries(raw, 3) == ("Same", "other", "third")


@pytest.mark.parametrize("raw", ["", "not json", "[1,2]", '{"queries": "oops"}', '{"q": []}'])
def test_parse_queries_rejects_unusable_replies(raw: str) -> None:
    assert parse_queries(raw, 3) == ()


# -- the model call ----------------------------------------------------------


async def test_simple_message_makes_no_model_call(fake_gateway: FakeGateway) -> None:
    built = await _build(fake_gateway, "How many leave days do I get?")

    assert built.queries == ("How many leave days do I get?",) and not built.rewritten
    assert fake_gateway.rewrite_prompts == []


async def test_follow_up_is_rewritten_using_the_conversation(fake_gateway: FakeGateway) -> None:
    fake_gateway.rewrite_raw = json.dumps({"queries": ["Ronaldo goals scored in 2016"]})

    built = await _build(
        fake_gateway,
        "and in 2016?",
        history="user: how many goals has Ronaldo scored?\nassistant: 900+",
    )

    assert built.queries == ("Ronaldo goals scored in 2016",) and built.rewritten
    # The conversation reached the model; otherwise it could not resolve the follow-up.
    assert "how many goals has Ronaldo scored" in fake_gateway.rewrite_prompts[0]


async def test_two_questions_become_two_queries(fake_gateway: FakeGateway) -> None:
    fake_gateway.rewrite_raw = json.dumps(
        {"queries": ["Ronaldo Ballon d'Or wins", "open incidents at the Pune site"]}
    )

    built = await _build(fake_gateway, "How many Ballon d'Ors? Any open incidents at Pune?")

    assert len(built.queries) == 2 and built.rewritten


async def test_model_failure_falls_back_to_the_message(fake_gateway: FakeGateway) -> None:
    fake_gateway.rewrite_fails = True

    built = await _build(fake_gateway, "and in 2016?", history="user: earlier question")

    assert built.queries == ("and in 2016?",) and not built.rewritten
    assert "unavailable" in built.note


async def test_unusable_reply_falls_back_to_the_message(fake_gateway: FakeGateway) -> None:
    fake_gateway.rewrite_raw = "I cannot do that"

    built = await _build(fake_gateway, "and in 2016?", history="user: earlier question")

    assert built.queries == ("and in 2016?",) and "unusable" in built.note


async def test_blank_message_builds_nothing(fake_gateway: FakeGateway) -> None:
    built = await _build(fake_gateway, "   ")

    assert built.queries == ()
