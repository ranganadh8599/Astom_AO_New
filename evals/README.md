# Retrieval evaluation

"Is semantic search choosing the right agent?" is a measurement, not an opinion. This folder
scores it against questions you label.

## What it measures

| Metric | Question it answers | If it is low, look at |
|---|---|---|
| retrieval recall / MRR | did the gateway's search put the right target in the shortlist, and near the top? | agent card wording, the embedding model, `RETRIEVAL_TOP_K` |
| gate accuracy | given that shortlist, did the coverage gate route answerable questions and reject the rest? | the gate prompt, the gate model |
| intent accuracy | were writes classified as `mutation`? | the gate prompt |

Retrieval and the gate are scored separately because they are fixed in different places.

## Use

```powershell
Copy-Item evals/golden.example.jsonl evals/golden.jsonl     # then replace with real questions
.\.venv\Scripts\python.exe evals/run_retrieval_eval.py --golden evals/golden.jsonl
```

It reads `.env`, so it measures what the running orchestrator would do against your gateway,
your embedding model and your agent cards. Exit status is non-zero below `--min-recall` or
`--min-gate` (default 0.9), so it can gate a deploy. Useful flags: `--no-gate` (score search
only), `--no-rewrite` (search with the raw message, to see what query building adds),
`--json out.json`.

`--no-rewrite` is worth running after any change to `QueryBuilder`: the gateway's embedding
search is phrasing-sensitive, and the query builder turns a sentence into a keyword phrase.

## Writing the question set

One JSON object per line (`#` lines are comments):

```json
{"id": "bio-1", "query": "Where was Ronaldo born?", "expect": ["ronaldo-agent"]}
{"id": "follow-1", "query": "and for Juventus?", "expect": ["ronaldo-agent"],
 "history": [{"role": "user", "content": "How many goals for Real Madrid?"}]}
{"id": "none-1", "query": "Boiling point of nitrogen?", "none": true}
{"id": "write-1", "query": "Delete incident INC-204", "expect": ["list_open_incidents"], "intent": "mutation"}
```

- `expect`: target names that should be retrieved. MCP tools can be written without the server
  prefix (`get_asset_status`).
- `none: true`: nothing registered can answer; the gate should reject it.
- Include follow-ups, two-topic questions and near-misses (a question about a *different*
  player). 30 to 50 rows is a good start. Add a row whenever a real question is mis-routed.
- Run it after every change to a card, the embedding model or the gate prompt.

### Intents are scored as contracts

`intent` is not decoration; it fixes what the gate is *supposed* to return:

| `intent` | Expected gate outcome | Why |
|---|---|---|
`"mutation"` | `no_match` (the read-only refusal) | a correctly refused write is a pass, not a coverage miss |
`"smalltalk"` | `smalltalk` | greetings are answered directly, never routed |
*(absent)* | `route`, or `no_match` when `none: true` | normal coverage judging |

Before this rule, a refused mutation scored as a gate failure, so a correct refusal looked
like a regression.

### A shipped set for the example suites

`evals/golden.jsonl` labels all 40 example targets (20 A2A agents, 20 MCP tools) plus
follow-ups, unanswerable questions, mutations and greetings — 59 cases. It is the set the
routing changes were measured against:

```
retrieval recall 100%   MRR 71%   gate accuracy 100%   intent accuracy 100%   (59/59)
```

Delete it and write your own before pointing the evaluation at a real catalogue.
