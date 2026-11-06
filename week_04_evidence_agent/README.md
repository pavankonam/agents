# Week 04: Evidence Agent

An **incident investigation agent** on a **free local model through Ollama** whose every claim has to be backed by something it actually retrieved. It queries synthetic telemetry (logs, metrics, deploys) through tools; every row a tool shows carries an evidence id like `ev_003`; findings and the final conclusion must cite those ids, and code rejects any citation the run never issued. The verdict comes from the scenario's ground truth, never from the model's summary. See [PRD.md](PRD.md) for the plan, [flow.md](flow.md) for how it works and [decision.md](decision.md) for why.

**Status:** Day 2 (2026-11-06). One scenario (`checkout_latency`: a payments deploy shrinks the db pool, checkout times out, with a search deploy and a cache warning as red herrings), the evidence ledger, four query tools and two citing tools, citation checks, **claim support checks** (a finding can carry a structured `check` that is verified against the rows it cites), the agent loop, a CLI, a scripted reference and six controls, a model quiz, 58 tests. Next: two more scenarios and a grading rubric (day 3).

## Run it

```bash
ollama pull qwen3:4b          # once
cd week_04_evidence_agent
export PYTHONPATH=src

python3 -m evidence_agent list                      # scenarios
python3 -m evidence_agent check                     # is Ollama up and the model pulled?
python3 -m evidence_agent run checkout_latency      # one investigation with qwen3:4b
python3 -m evidence_agent run checkout_latency --json
EVIDENCE_AGENT_MODEL=llama3.2 python3 -m evidence_agent run checkout_latency --max-steps 8
```

### Record the real baseline (one command, please run once this week)

```bash
python3 quiz/quiz_model.py --record results/qwen3_4b.jsonl
```

This appends one JSON report per scenario to `results/qwen3_4b.jsonl`, with every finding, accepted or rejected, and the conclusion. The daily automation cannot reach Ollama on the Mac, so the real numbers depend on this run (D11).

| Exit code | Meaning |
| --- | --- |
| 0 | passed |
| 1 | ran but failed (wrong root cause, no conclusion, step or turn limit) |
| 2 | usage: bad arguments or unknown scenario |
| 4 | Ollama not ready |

## Tests and quiz (no Ollama needed)

```bash
python3 -m pytest -q
python3 quiz/quiz_model.py --fake
```

`--fake` plays the scripted reference (must pass with no rejected finding and every check supported) and six controls: a text only answer, a conclusion citing an invented id, a rejected finding followed by the reference, a conclusion blaming the red herring service, a finding whose cited row contradicts it, and a finding citing a real but unrelated row. Each must end exactly as declared in `src/evidence_agent/scripted.py`, including the support status of every finding.

## Claim support (day 2)

A finding may carry a `check`, the claim in a form code can verify against the rows the finding cites:

```json
{"claim": "checkout p95 went above 2s at 14:05",
 "evidence_ids": ["ev_006", "ev_007"],
 "check": {"service": "checkout", "field": "p95_latency_ms", "op": ">", "value": 2000, "at": "14:05"}}
```

`field` is a metric name, or `level`/`message` for logs, or `version`/`note` for deploys. `op` is one of `>`, `>=`, `<`, `<=`, `==`, `contains` (words like `gt` are accepted). Only the cited rows are looked at.

| Status | Meaning | Finding |
| --- | --- | --- |
| supported | a relevant cited row satisfies the check | accepted |
| contradicted | relevant cited rows exist and none satisfies it | rejected, rows and values named |
| unsupported | no cited row is about that service, field (and time) | rejected |
| invalid | the check is malformed | rejected |
| unchecked | no check, or the ids were already rejected | accepted only if the ids are fine |

## Layout

| File | What it does |
| --- | --- |
| `src/evidence_agent/telemetry.py` | `Record`, `Scenario`, the `checkout_latency` data |
| `src/evidence_agent/ledger.py` | `EvidenceLedger`: issues `ev_NNN` ids, the only citable ids |
| `src/evidence_agent/support.py` | claim checks: parse, compare against the cited rows, support status |
| `src/evidence_agent/investigation.py` | tools, argument validation, citation checks, findings, verdict |
| `src/evidence_agent/agent.py` | `run_investigation` loop, system prompt, report printing |
| `src/evidence_agent/scripted.py` | scripted reference and controls |
| `src/evidence_agent/cli.py` | `list`, `check`, `run` |
| `src/evidence_agent/llm.py` | Ollama client and fake client (copied from week 03) |
