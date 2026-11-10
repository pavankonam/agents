# Week 04: Evidence Agent

An **incident investigation agent** on a **free local model through Ollama** whose every claim has to be backed by something it actually retrieved. It queries synthetic telemetry (logs, metrics, deploys) through tools; every row a tool shows carries an evidence id like `ev_003`; findings and the final conclusion must cite those ids, and code rejects any citation the run never issued. The verdict comes from the scenario's ground truth, never from the model's summary. See [PRD.md](PRD.md) for the plan, [flow.md](flow.md) for how it works and [decision.md](decision.md) for why.

**Status:** Day 6 (2026-11-10). Three scenarios, each with a trap: `checkout_latency` (a payments deploy shrinks the db pool; a search deploy and a cache warning are red herrings), `config_push` (a gateway config push cuts the upstream timeout to 300 ms; a worker CPU spike is the red herring) and `dependency_outage` (an external email vendor goes down; the first deploy is innocent). The evidence ledger, four query tools and two citing tools, citation checks, claim support checks, a **grading rubric with a score out of 100 per run**, **bounds** (a query budget, an incident time window and an operator kill switch, with every refusal and stop in an audit log with who and why), **verified memory across runs** (findings recalled only after they are re-checked against the current data), **an eval over every scenario and seeded variants** (noise rows, row order and evidence id order change per seed, so memorised ids fail), the agent loop, a CLI, a scripted reference per scenario and fourteen controls, a model quiz, 114 tests. Next: real qwen3:4b results and close out (day 7).

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

# bounds (day 4)
python3 -m evidence_agent run checkout_latency --max-queries 3 --audit audit.jsonl
python3 -m evidence_agent run config_push --kill-file stop.txt
#   from another terminal, to stop it:  echo "pavan: taking over by hand" > stop.txt

# memory (day 5): the second run recalls the first run's verified findings
python3 -m evidence_agent run checkout_latency --memory memory.json
python3 -m evidence_agent run checkout_latency --memory memory.json

# eval (day 6): every scenario on seeds 0..N-1 of seeded variants
python3 -m evidence_agent eval --seeds 3                      # live, qwen3:4b
python3 -m evidence_agent eval --seeds 3 --markdown > results/qwen3_4b_eval.md
python3 -m evidence_agent eval --seeds 5 --json --record results/qwen3_4b_eval.jsonl --min-pass-rate 0.5
python3 -m evidence_agent eval --fake --seeds 3               # scripted references, no Ollama
```

### Record the real baseline (one command, please run once this week)

```bash
python3 quiz/quiz_model.py --record results/qwen3_4b.jsonl
python3 -m evidence_agent eval --seeds 3 --markdown > results/qwen3_4b_eval.md
```

This appends one JSON report per scenario (now three, each with its `score`) to `results/qwen3_4b.jsonl`, with every finding, accepted or rejected, and the conclusion. The daily automation cannot reach Ollama on the Mac, so the real numbers depend on this run (D11).

| Exit code | Meaning |
| --- | --- |
| 0 | passed |
| 1 | ran but failed (wrong root cause, no conclusion, step or turn limit, killed) |
| 2 | usage: bad arguments or unknown scenario |
| 4 | Ollama not ready |

## Tests and quiz (no Ollama needed)

```bash
python3 -m pytest -q
python3 quiz/quiz_model.py --fake
```

`--fake` runs two eval checks (replayed references pass 9/9 on 3 seeds; memorised ids fail all 6 variants) and plays the scripted reference of every scenario (must pass with no rejected finding, every check supported, a score of 100 and one `concluded` stop in the audit log) and fourteen controls: a text only answer, a conclusion citing an invented id, a rejected finding followed by the reference, a conclusion blaming the red herring service, a finding whose cited row contradicts it, a finding citing a real but unrelated row, blaming the CPU spike on `config_push`, blaming the innocent first deploy on `dependency_outage`, naming the right service while citing no cause row, running out of a query budget of 2, querying before the incident window, an operator kill during the third turn, a run that recalls the reference run's three findings and concludes after one query, and the same with two stale entries that must be dropped. Each must end exactly as declared in `src/evidence_agent/scripted.py`, including the support status of every finding, its rubric score, its audit log and its recall counts.

## Eval (day 6)

`eval` runs every scenario (or `--scenario NAME`, repeatable) on seeds 0 to N-1 (`--seeds`, default 3). Seed 0 is the scenario as written. Every other seed is a variant of the same incident:

* 3 to 6 harmless INFO log rows (health checks, heartbeats, gc pauses) inside the incident window,
* a different order among rows that share a minute,
* evidence ids handed out in a seeded order (`ev_937` instead of `ev_002`).

The root cause and cause rows do not change, but an id only means something inside the run that issued it. The live model gets the seed too (Ollama `options.seed`).

| Reported | Meaning |
| --- | --- |
| pass rate, mean score | over all runs, and per scenario |
| rejected citations | finding or conclude calls refused for an unknown or missing id |
| contradicted, unsupported | findings whose check the cited rows contradict or do not cover |
| failure kinds | `wrong_root_cause`, or the end reason: `no_conclusion`, `step_limit`, `turn_limit`, `killed` |

Output as lines, `--json` or `--markdown`; `--record PATH` appends each run's full report with its seed and kind. Exit 0 when the pass rate is at least `--min-pass-rate` (default 1.0), 1 when not, 2 on usage errors, 4 when Ollama is not ready. `--fake` replays the scripted references through `ReplayClient`, which reads the ids this run's tools returned and rewrites the script's ids by row; the fake table is in [results/fake_eval.md](results/fake_eval.md). The same scripts with memorised ids fail every variant, which `quiz_model.py --fake` checks.

## Memory (day 5)

`run --memory PATH` keeps verified findings across runs in a small JSON file.

* **Stored:** after a run, every accepted finding whose check was `supported`, with the rows that backed it. Unchecked findings and conclusions are never stored. A finding with the same check replaces the old one.
* **Re-checked:** before the next run on the same scenario, each stored row is found again by kind, time, service and metric name (not by value), and the stored check runs again on the current values with the same code that checks live findings.
* **Recalled or dropped:** a finding that still holds has its rows issued evidence ids before the first turn (no query spent) and is shown to the model with the question. A missing row or a check that no longer holds drops it with the reason, and it is forgotten.

```text
  recall: dropped 'checkout p95 was above 2s already at 14:00': claim now contradicted: current rows contradict checkout p95_latency_ms > 2000 at 14:00: 14:00 checkout p95_latency_ms=230 has 230
  recall: kept 'payments v2.3.1 at 14:02 cut the db pool from 50 to 5' as ev_001
  memory: recalled 3, dropped 2, stored 1 verified finding(s)
```

## Bounds and audit (day 4)

| Bound | Rule | Refused or stopped as |
| --- | --- | --- |
| query budget | `search_logs`, `get_metric`, `list_deploys` cost 1 each, default 8 (`--max-queries`) | refused `query_budget` by system |
| incident window | `since`/`until` (HH:MM) on query tools must lie in the scenario window; they also filter rows | refused `time_window` by system |
| kill switch | an operator trips it from outside the loop (`KillSwitch.trigger(who, why)` or `--kill-file`); checked before every model turn and tool call | stop `killed` by the operator |
| steps, turns | `--max-steps`, turn limit | stop `step_limit` / `turn_limit` by system |

Every run ends with exactly one audited stop (`concluded` and `no_conclusion` are by `agent`). The audit log is printed with the report, included in `--json`, and appended to a file with `--audit PATH`:

```text
  audit: step 3 refused query_budget by system: query budget of 2 used up; report findings or conclude with the evidence you already have
  audit: step 6 stop concluded by agent: concluded payments
```

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
| `src/evidence_agent/bounds.py` | query budget tools, incident window rule, `KillSwitch`, `FileKillSwitch`, `AuditEntry` |
| `src/evidence_agent/grading.py` | rubric: score out of 100 per run, per criterion detail |
| `src/evidence_agent/ledger.py` | `EvidenceLedger`: issues `ev_NNN` ids, the only citable ids |
| `src/evidence_agent/support.py` | claim checks: parse, compare against the cited rows, support status |
| `src/evidence_agent/memory.py` | `FindingMemory`: store verified findings, re-check them by row identity, recall or drop |
| `src/evidence_agent/investigation.py` | tools, argument validation, citation checks, findings, verdict |
| `src/evidence_agent/agent.py` | `run_investigation` loop, system prompt, report printing |
| `src/evidence_agent/scripted.py` | scripted reference and controls |
| `src/evidence_agent/variants.py` | seeded scenario variants: noise rows, same minute reorder, ledger id seed |
| `src/evidence_agent/evaluation.py` | `evaluate`, `EvalRun`, `EvalSummary` (lines, JSON, Markdown), `ReplayClient` |
| `src/evidence_agent/cli.py` | `list`, `check`, `run` (with `--max-queries`, `--kill-file`, `--audit`, `--memory`), `eval` |
| `src/evidence_agent/llm.py` | Ollama client and fake client (copied from week 03) |
