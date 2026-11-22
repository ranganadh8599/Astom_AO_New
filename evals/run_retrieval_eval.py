"""Score retrieval and the coverage gate against a labelled question set.

    python evals/run_retrieval_eval.py --golden evals/golden.jsonl

Uses the same settings as the orchestrator (.env / environment), so it measures exactly
what production would do: your gateway's search, your embedding model, your agent cards.
Run it after every change to an agent card, the embedding model, or the gate prompt.

Exit status is non-zero when a threshold is missed, so it can gate a deployment.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from evals.retrieval_eval import CaseResult, load_cases, run_case, summarize  # noqa: E402
from orchestrator.config import Settings, load_dotenv  # noqa: E402
from orchestrator.gateway import LiteLLMGateway  # noqa: E402
from orchestrator.routing.coverage_gate import CoverageGate  # noqa: E402
from orchestrator.routing.query_builder import QueryBuilder  # noqa: E402
from orchestrator.routing.target_catalog import TargetCatalog  # noqa: E402


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _print(results: list[CaseResult], summary: dict) -> None:
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"[{status}] {r.case.id}: {r.case.query}")
        if r.queries and r.queries != (r.case.query,):
            print(f"        searched as : {' | '.join(r.queries)}")
        if r.case.expect:
            print(f"        expected    : {', '.join(r.case.expect)}  "
                  f"(found {len(r.found)}/{len(r.case.expect)}, best rank {r.best_rank or '-'})")
        if r.gate_outcome:
            named = f" named={','.join(r.gate_named)}" if r.gate_named else ""
            print(f"        gate        : {r.gate_outcome} intent={r.gate_intent}{named}")
        if not r.passed:
            print(f"        retrieved   : {', '.join(r.retrieved) or '(nothing)'}")
        if r.error:
            print(f"        error       : {r.error}")
    print()
    print(f"cases {summary['cases']}  passed {summary['passed']}  errors {summary['errors']}")
    print(f"retrieval recall {_pct(summary['retrieval_recall'])}   "
          f"MRR {_pct(summary['retrieval_mrr'])}   "
          f"gate accuracy {_pct(summary['gate_accuracy'])}   "
          f"intent accuracy {_pct(summary['intent_accuracy'])}")


async def _run(args: argparse.Namespace) -> int:
    load_dotenv()
    settings = Settings.from_env()
    settings.validate()
    cases = load_cases(Path(args.golden))
    if not cases:
        print(f"{args.golden}: no cases", file=sys.stderr)
        return 2

    async with LiteLLMGateway(settings) as gateway:
        catalog = TargetCatalog(gateway, settings)
        builder = (
            QueryBuilder(gateway, settings.effective_rewrite_model,
                         max_queries=settings.query_rewrite_max_queries)
            if settings.can_rewrite_queries and not args.no_rewrite else None
        )
        gate = (
            CoverageGate(gateway, settings.effective_gate_model)
            if settings.coverage_gate_enabled and not args.no_gate else None
        )
        results = [await run_case(c, catalog=catalog, builder=builder, gate=gate) for c in cases]

    summary = summarize(results)
    _print(results, summary)
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2), encoding="utf-8")

    misses = []
    if (summary["retrieval_recall"] or 1.0) < args.min_recall:
        misses.append(f"retrieval recall below {args.min_recall:.0%}")
    if (summary["gate_accuracy"] or 1.0) < args.min_gate:
        misses.append(f"gate accuracy below {args.min_gate:.0%}")
    if summary["errors"]:
        misses.append(f"{summary['errors']} case(s) errored")
    for miss in misses:
        print(f"THRESHOLD MISSED: {miss}", file=sys.stderr)
    return 1 if misses else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--golden", default="evals/golden.jsonl", help="labelled questions (JSON lines)")
    parser.add_argument("--min-recall", type=float, default=0.9)
    parser.add_argument("--min-gate", type=float, default=0.9)
    parser.add_argument("--no-gate", action="store_true", help="score retrieval only")
    parser.add_argument("--no-rewrite", action="store_true", help="search with the raw message")
    parser.add_argument("--json", help="also write the summary to this file")
    sys.exit(asyncio.run(_run(parser.parse_args())))


if __name__ == "__main__":
    main()
