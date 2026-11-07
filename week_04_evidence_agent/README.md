# Week 04: Evidence Agent

An **incident investigation agent** on a **free local model through Ollama** whose every claim has to be backed by something it actually retrieved. It queries synthetic telemetry (logs, metrics, deploys) through tools; every row a tool shows carries an evidence id like `ev_003`; findings and the final conclusion must cite those ids, and code rejects any citation the run never issued. The verdict comes from the scenario's ground truth, never from the model's summary. See [PRD.md](PRD.md) for the plan, [flow.md](flow.md) for how it works and [decision.md](decision.md) for why.

**Status:** Day 3 (2026-11-07). Three scenarios, each with a trap: `checkout_latency` (a payments deploy shrinks the db pool; a search deploy and a cache warning are red herrings), `config_push` (a gateway config push cuts the upstream timeout to 300 ms; a worker CPU spike is the red herring) and `dependency_outage` (an external email vendor goes down; the first deploy is innocent). The evidence ledger, four query tools and two citing tools, citation checks, claim support checks, a **grading rubric with a score out of 100 per run**, the agent loop, a CLI, a scripted reference per scenario and nine controls, a model quiz, 71 tests. Next: bounds and a kill switch (day 4).

## Run it

```bash
ollama pull qwen3:4b          # once
cd week_04_evidence_agent
export PYTHONPATH=src

python3 -m evidence_agent list                      # scenarios
python3 -m evidence_agent check                     # is Ollama up and the model pulled?
python3 -m evidence_agent run checkout_latency      # one investigation with qwen3:4b
python3 -m evidence_agent run config_push
python3 -m evidence_agent run dependency_outage
python3 -m evidence_agent run checkout_latency --json
EVIDENCE_AGENT_MODEL=llama3.2 python3 -m evidence_agent run checkout_latency --max-steps 8
```

### Record the real baseline (one command, please run once this week)

```bash
python3 quiz/quiz_model.py --record results/qwen3_4b.jsonl
```

This appends one JSON report per scenario (now three, each with its `score`) to `results/qwen3_4b.jsonl`, with every finding, accepted or rejected, and the conclusion. The daily automation cannot reach Ollama on the Mac, so the real numbers depend on this run (D11).

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

`--fake` plays the scripted reference of every scenario (must pass with no rejected finding, every check supported and a score of 100) and nine controls: a text only answer, a conclusion citing an invented id, a rejected finding followed by the reference, a conclusion blaming the red herring service, a finding whose cited row contradicts it, a finding citing a real but unrelated row, blaming the CPU spike on `config_push`, blaming the innocent first deploy on `dependency_outage`, and naming the right service while citing no cause row. Each must end exactly as declared in `src/evidence_agent/scripted.py`, including the support status of every finding and its rubric score.

## Grading rubric (day 3)

`passed` is strict: concluded with the true root cause service. The **score** says how good the investigation was:

| Criterion | Points | Earned when |
| --- | --- | --- |
| root_cause | 40 | the conclusion names the true root cause service |
| cause_evidence | 30 | the conclusion cites at least one row that shows the cause |
| no_contradicted | 20 | no finding, accepted or rejected, was contradicted by its rows |
| efficiency | 10 | steps within the reference + 2; then 2 points off per extra step |

A run without a conclusion scores 0. Example: `cause_not_cited` names `email_vendor` correctly but cites only a signup log, so it passes with 70.

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
| `src/evidence_agent/telemetry.py` | `Record`, `Scenario`, the three scenarios with cause rows marked |
| `src/evidence_agent/grading.py` | rubric: score out of 100 per run, per criterion detail |
| `src/evidence_agent/ledger.py` | `EvidenceLedger`: issues `ev_NNN` ids, the only citable ids |
| `src/evidence_agent/support.py` | claim checks: parse, compare against the cited rows, support status |
| `src/evidence_agent/investigation.py` | tools, argument validation, citation checks, findings, verdict |
| `src/evidence_agent/agent.py` | `run_investigation` loop, system prompt, report printing |
| `src/evidence_agent/scripted.py` | scripted reference and controls |
| `src/evidence_agent/cli.py` | `list`, `check`, `run` |
| `src/evidence_agent/llm.py` | Ollama client and fake client (copied from week 03) |
