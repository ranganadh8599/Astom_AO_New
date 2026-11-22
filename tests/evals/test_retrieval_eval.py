"""The evaluation scoring, run against the fake gateway (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.retrieval_eval import Case, load_cases, run_case, summarize
from orchestrator.gateway import LiteLLMGateway
from orchestrator.routing.coverage_gate import CoverageGate
from orchestrator.routing.target_catalog import TargetCatalog
from tests.conftest import FakeGateway, make_settings


def _parts(fake: FakeGateway):
    settings = make_settings()
    gateway = LiteLLMGateway(settings, client=fake.client())
    return TargetCatalog(gateway, settings), CoverageGate(gateway, "test/planner")


async def test_an_answerable_question_passes(fake_gateway: FakeGateway) -> None:
    fake_gateway.agent_search_enabled = True
    catalog, gate = _parts(fake_gateway)
    case = Case(id="a", query="leave policy", expect=("hr-policy-agent",))

    result = await run_case(case, catalog=catalog, builder=None, gate=gate)

    assert result.retrieval_ok and result.best_rank == 1 and result.passed


async def test_a_missing_target_fails_retrieval_and_says_what_was_retrieved(
    fake_gateway: FakeGateway,
) -> None:
    fake_gateway.agent_search_enabled = True
    catalog, _ = _parts(fake_gateway)
    case = Case(id="b", query="leave policy", expect=("does-not-exist",))

    result = await run_case(case, catalog=catalog, builder=None, gate=None)

    assert result.retrieval_ok is False and not result.passed and result.retrieved


async def test_an_unanswerable_question_must_be_rejected_by_the_gate(
    fake_gateway: FakeGateway,
) -> None:
    fake_gateway.gate_no_match = True
    catalog, gate = _parts(fake_gateway)
    case = Case(id="c", query="boiling point of nitrogen", none=True)

    result = await run_case(case, catalog=catalog, builder=None, gate=gate)

    assert result.gate_ok is True and result.passed


async def test_a_gate_that_accepts_an_unanswerable_question_fails(
    fake_gateway: FakeGateway,
) -> None:
    catalog, gate = _parts(fake_gateway)
    case = Case(id="d", query="leave policy", none=True)

    result = await run_case(case, catalog=catalog, builder=None, gate=gate)

    assert result.gate_ok is False and not result.passed


async def test_a_refused_mutation_is_a_pass_not_a_coverage_miss(
    fake_gateway: FakeGateway,
) -> None:
    fake_gateway.default_mutation = True
    catalog, gate = _parts(fake_gateway)
    case = Case(id="w", query="cancel ticket INC-204", expect=("hr-policy-agent",),
                intent="mutation")

    result = await run_case(case, catalog=catalog, builder=None, gate=gate)

    assert result.gate_outcome == "no_match"
    assert result.gate_ok is True and result.intent_ok is True and result.passed


async def test_a_mutation_that_gets_routed_fails(fake_gateway: FakeGateway) -> None:
    fake_gateway.agent_search_enabled = True
    catalog, gate = _parts(fake_gateway)
    case = Case(id="w2", query="leave policy", expect=("hr-policy-agent",),
                intent="mutation")

    result = await run_case(case, catalog=catalog, builder=None, gate=gate)

    assert result.gate_outcome == "route" and result.gate_ok is False and not result.passed


async def test_smalltalk_is_scored_against_its_own_outcome(fake_gateway: FakeGateway) -> None:
    fake_gateway.gate_raw = json.dumps(
        {"intent": "smalltalk", "can_answer": False, "targets": [], "reason": "greeting",
         "confidence": 0.95}
    )
    catalog, gate = _parts(fake_gateway)
    case = Case(id="hi", query="hi there", none=True, intent="smalltalk")

    result = await run_case(case, catalog=catalog, builder=None, gate=gate)

    assert result.gate_outcome == "smalltalk"
    assert result.gate_ok is True and result.intent_ok is True and result.passed


async def test_summary_counts_and_lists_failures(fake_gateway: FakeGateway) -> None:
    fake_gateway.agent_search_enabled = True
    catalog, gate = _parts(fake_gateway)
    good = await run_case(Case(id="good", query="leave policy", expect=("hr-policy-agent",)),
                          catalog=catalog, builder=None, gate=gate)
    bad = await run_case(Case(id="bad", query="leave policy", expect=("nope",)),
                         catalog=catalog, builder=None, gate=None)

    summary = summarize([good, bad])

    assert summary["cases"] == 2 and summary["passed"] == 1
    assert summary["retrieval_recall"] == 0.5 and summary["failures"] == ["bad"]


def test_golden_file_parsing(tmp_path: Path) -> None:
    path = tmp_path / "g.jsonl"
    path.write_text(
        "# comment\n"
        + json.dumps({"id": "x", "query": "q", "expect": ["a"]}) + "\n"
        + json.dumps({"query": "q2", "none": True}) + "\n",
        encoding="utf-8",
    )

    cases = load_cases(path)

    assert [c.id for c in cases] == ["x", "case-3"] and cases[1].none


def test_golden_file_with_a_bom_is_still_readable(tmp_path: Path) -> None:
    """Windows editors prepend a BOM; that must not look like bad JSON."""
    path = tmp_path / "g.jsonl"
    path.write_bytes(
        b"\xef\xbb\xbf" + json.dumps({"id": "b", "query": "q", "expect": ["a"]}).encode()
        + b"\n"
    )

    cases = load_cases(path)

    assert [c.id for c in cases] == ["b"]


@pytest.mark.parametrize(
    "row", [{"id": "x"}, {"query": "q"}, {"query": "q", "expect": ["a"], "none": True}]
)
def test_malformed_cases_are_rejected_with_a_line_number(tmp_path: Path, row: dict) -> None:
    path = tmp_path / "g.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="g.jsonl:1"):
        load_cases(path)


def test_the_shipped_example_file_is_valid() -> None:
    cases = load_cases(Path(__file__).resolve().parents[2] / "evals" / "golden.example.jsonl")
    assert len(cases) >= 8 and any(c.none for c in cases) and any(c.history for c in cases)
