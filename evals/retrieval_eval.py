"""Scoring logic for the retrieval evaluation (no network, no CLI).

Kept separate from ``run_retrieval_eval.py`` so the scoring can be unit-tested against the
fake gateway; the CLI only wires real settings into it.

What is measured, per labelled question:

* **retrieval** - did the gateway's search put every expected target in the shortlist,
  and how high? (``recall``, ``rank``, and MRR over the set)
* **coverage gate** - given that shortlist, did the gate route a question that has an
  answer and reject one that has none? Did it classify intent correctly?

Retrieval and gate are scored separately on purpose: a wrong answer is fixed differently
depending on which one missed (card wording and embedding model vs. the gate prompt).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orchestrator.gateway import Target
from orchestrator.observability.trace_context import Lineage, TraceContext
from orchestrator.routing.coverage_gate import (
    OUTCOME_NO_MATCH,
    OUTCOME_SMALLTALK,
    CoverageGate,
    CoverageVerdict,
)
from orchestrator.routing.query_builder import QueryBuilder
from orchestrator.routing.target_catalog import TargetCatalog


@dataclass(frozen=True)
class Case:
    """One labelled question.

    ``expect``  names the targets that should be retrieved. An entry matches a target by
                exact name, by MCP tool name (``get_asset_status``), or as the suffix of a
                server-prefixed name (``field-ops-mcp-get_asset_status``).
    ``none``    marks a question that no registered target can answer.
    ``intent``  optionally pins the gate's read / mutation classification.
    ``history`` earlier turns, to exercise follow-up rewriting.
    """

    id: str
    query: str
    expect: tuple[str, ...] = ()
    none: bool = False
    intent: str = ""
    history: tuple[dict[str, str], ...] = ()


@dataclass
class CaseResult:
    case: Case
    queries: tuple[str, ...] = ()
    retrieved: list[str] = field(default_factory=list)
    found: list[str] = field(default_factory=list)
    best_rank: int | None = None
    gate_outcome: str = ""
    gate_named: tuple[str, ...] = ()
    gate_intent: str = ""
    error: str = ""

    @property
    def recall(self) -> float | None:
        if not self.case.expect:
            return None
        return len(self.found) / len(self.case.expect)

    @property
    def retrieval_ok(self) -> bool | None:
        if not self.case.expect:
            return None
        return len(self.found) == len(self.case.expect)

    @property
    def gate_ok(self) -> bool | None:
        if not self.gate_outcome:
            return None
        # A labelled intent is a contract, not a hope. A mutation is *supposed* to be
        # refused (no_match) and a greeting is supposed to be answered directly
        # (smalltalk), so neither is a coverage miss to be scored as a failure.
        # Checked before `none`, because those rows also carry `none: true`.
        if self.case.intent == "mutation":
            return self.gate_outcome == OUTCOME_NO_MATCH
        if self.case.intent == "smalltalk":
            return self.gate_outcome == OUTCOME_SMALLTALK
        if self.case.none:
            return self.gate_outcome == OUTCOME_NO_MATCH
        if self.gate_outcome == OUTCOME_NO_MATCH:
            return False
        if self.gate_named and self.case.expect:
            return any(_matches(e, n) for e in self.case.expect for n in self.gate_named)
        return True

    @property
    def intent_ok(self) -> bool | None:
        if not self.case.intent or not self.gate_outcome:
            return None
        return self.gate_intent == self.case.intent

    @property
    def passed(self) -> bool:
        checks = (self.retrieval_ok, self.gate_ok, self.intent_ok)
        return not self.error and all(c is not False for c in checks)


def _matches(expected: str, name: str, tool_name: str = "") -> bool:
    return expected == name or expected == tool_name or name.endswith(f"-{expected}")


def load_cases(path: Path) -> list[Case]:
    cases: list[Case] = []
    # ``utf-8-sig`` rather than ``utf-8``: Windows editors and PowerShell's
    # ``Set-Content -Encoding UTF8`` prepend a BOM, which json.loads rejects with
    # "Unexpected UTF-8 BOM". A labelled file is written by hand, so tolerate it.
    for number, line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: not valid JSON ({exc})") from exc
        if "query" not in row:
            raise ValueError(f"{path}:{number}: every case needs a 'query'")
        expect = tuple(row.get("expect") or ())
        if bool(row.get("none")) == bool(expect):
            raise ValueError(
                f"{path}:{number}: a case needs either 'expect' (targets) or 'none': true"
            )
        cases.append(
            Case(
                id=str(row.get("id") or f"case-{number}"),
                query=str(row["query"]),
                expect=expect,
                none=bool(row.get("none")),
                intent=str(row.get("intent") or ""),
                history=tuple(row.get("history") or ()),
            )
        )
    return cases


def history_block(history: Sequence[dict[str, str]]) -> str:
    return "\n".join(f"{t.get('role', 'user')}: {t.get('content', '')}" for t in history)


async def run_case(
    case: Case,
    *,
    catalog: TargetCatalog,
    builder: QueryBuilder | None,
    gate: CoverageGate | None,
) -> CaseResult:
    result = CaseResult(case=case)
    trace, lineage = TraceContext.root(), Lineage.root()
    try:
        queries: tuple[str, ...] = (case.query,)
        if builder is not None:
            built = await builder.build(
                case.query, history=history_block(case.history), trace=trace, lineage=lineage
            )
            queries = built.queries or queries
        result.queries = queries

        retrieval = await catalog.retrieve_for(case.query, trace, queries=queries)
        targets: list[Target] = list(retrieval.records)
        result.retrieved = [t.agent_name for t in targets]

        for expected in case.expect:
            ranks = [
                index
                for index, t in enumerate(targets, start=1)
                if _matches(expected, t.agent_name, t.tool_name)
            ]
            if ranks:
                result.found.append(expected)
                result.best_rank = min(ranks + ([result.best_rank] if result.best_rank else []))

        if gate is not None:
            verdict: CoverageVerdict | None = await gate.assess(
                case.query,
                targets,
                trace=trace,
                lineage=lineage,
                history=history_block(case.history),
            )
            if verdict is None:
                result.error = "coverage gate could not be consulted"
            else:
                result.gate_outcome = verdict.outcome
                result.gate_named = tuple(verdict.named)
                result.gate_intent = verdict.intent
    except Exception as exc:  # one bad case must not stop the run
        result.error = f"{type(exc).__name__}: {exc}"
    return result


def summarize(results: Iterable[CaseResult]) -> dict[str, Any]:
    rows = list(results)

    def rate(values: list[bool | None]) -> float | None:
        scored = [v for v in values if v is not None]
        return sum(scored) / len(scored) if scored else None

    reciprocal = [1 / r.best_rank for r in rows if r.case.expect and r.best_rank]
    expecting = [r for r in rows if r.case.expect]
    return {
        "cases": len(rows),
        "passed": sum(r.passed for r in rows),
        "errors": sum(bool(r.error) for r in rows),
        "retrieval_recall": rate([r.retrieval_ok for r in rows]),
        "retrieval_mrr": (sum(reciprocal) / len(expecting)) if expecting else None,
        "gate_accuracy": rate([r.gate_ok for r in rows]),
        "intent_accuracy": rate([r.intent_ok for r in rows]),
        "failures": [r.case.id for r in rows if not r.passed],
    }
