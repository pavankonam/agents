# PRD: Evidence Agent

**Week:** 04 (2026-11-05 to 2026-11-11)
**Stack:** Python 3.10+, Ollama (local, free), standard library only

## 1. Why this project

The research pass on 2026-11-05 (news of 2026-10-28 to 2026-11-03) kept pointing at one gap: agents that investigate and report are moving into operations work, and the advice around them is all about **evidence and bounds**.

* Honeycomb's Personal and Team **AI SRE agents** (early access, 2026-11-03) run goal oriented investigations over telemetry, remember findings across runs and act only within bounds the team sets. The commentary recommends requiring **evidence links to the traces and queries** behind each finding.
* CrowdStrike's **AI Kill Switch** (2026-11-03) stops a misbehaving agent and blocks its relaunch, with the advice to check that the audit trail records who stopped it and why.
* AWS's multi agent engineering blueprint (2026-11-03) pairs model agents with **deterministic Python checks** for the rules, and notes that an evaluator can wrongly score a correct refusal as a failure.
* Anthropic's dataset monitor research (2026-11-01): items that each pass a check can still add up to the wrong result, so check the combined effect, not only the rows.

This project builds a small incident investigation agent for a local model. It queries synthetic telemetry (logs, metrics, deploys) through tools, and **every finding and the conclusion must cite evidence ids that a tool actually returned in this run**. Citations are checked by code, then (from day 2) each claim is checked against the rows it cites, and the verdict is computed from the scenario's ground truth, never from the model's words. Week 01 controlled what tools an agent may call, week 02 what instructions it loads, week 03 whether it did the job; week 04 asks whether what it **says** is backed by what it **saw**.

Source: [AI agent news, week of 2026-11-03](https://aiagentstore.ai/ai-agent-news/this-week) (all four items above).

## 2. Goals

1. Query tools over in memory telemetry that tag every returned row with an evidence id, and a ledger that is the only source of citable ids.
2. Findings and a conclusion that are rejected when they cite nothing or an id the run never saw, with the reason sent back so the model can fix it.
3. Structured claims checked against the cited rows: supported, contradicted or unsupported.
4. Scenarios with ground truth and red herrings, graded on root cause, evidence quality and wasted steps.
5. Bounds: a query budget, a time window rule and an operator kill switch with an audit trail.
6. Memory of verified findings across runs that is re-checked against the current data before reuse.

## 3. Non goals

* No real observability backend (Honeycomb, Prometheus, Loki). Data is synthetic and in process.
* No remediation actions (restart, rollback). The agent only reads and reports.
* No cloud or paid LLM APIs.

## 4. Users

An on call engineer who wants to know whether a local model's incident summary can be trusted, and exactly which claims are backed by which rows.

## 5. Daily milestones

* [x] **Day 1 (Thu 11/05):** Research, PRD, decision log, flow, quiz. Telemetry records and the `checkout_latency` scenario (4 services, 20 records, a red herring search deploy and cache warning), evidence ledger, `Investigation` with 4 query tools (`list_services`, `search_logs`, `get_metric`, `list_deploys`) and 2 citing tools (`report_finding`, `conclude`), argument validation, step limit, citation checks (no evidence, unknown id), verdict from ground truth, agent loop, LLM client copied from week 03, CLI (`list`, `check`, `run --json --record`), scripted reference and 4 controls, quiz_model with `--record`, tests.
* [x] **Day 2 (Fri 11/06):** Claim support: findings carry an optional structured claim (service, metric or log field, comparison, value, time); each one is checked against the rows it cites and marked supported, contradicted or unsupported. A finding that cites real rows that do not back it is no longer accepted silently. Done: `support.py` (`check` argument on `report_finding`, statuses supported, contradicted, unsupported, invalid, unchecked), non supported checks reject the finding with the rows named, support counts in reports and JSON, reference findings all carry checks, 2 new controls (contradicted claim, irrelevant citation), 58 tests.
* [ ] **Day 3 (Sat 11/07):** Two more scenarios (a bad config push with a misleading CPU spike, a dependency outage where the first deploy is innocent), a grading rubric (root cause, cited evidence covers the cause, no contradicted claims, steps over a reference) and a per scenario score.
* [ ] **Day 4 (Sun 11/08):** Bounds: a query budget per run, a time window rule (queries outside the incident window are refused) and a kill switch an operator can trigger from outside the loop; every stop lands in an audit log with who and why.
* [ ] **Day 5 (Mon 11/09):** Memory: verified findings are stored with their evidence rows; the next run can recall them, but a recalled finding is re-checked against the current scenario data and dropped if it no longer holds.
* [ ] **Day 6 (Tue 11/10):** Eval: `eval` over all scenarios and N seeds (seeded noise rows and id order), a report with pass rate, rejected citations, unsupported claims and failure kinds, `--json` and `--markdown`, fixed exit codes.
* [ ] **Day 7 (Wed 11/11):** Close out: real model results (qwen3:4b) in `results/`, README results table, retro in decision.md, project closed in state.json.

## 6. Success criteria

* `python3 -m pytest -q` passes with the fake LLM, no Ollama needed.
* `python3 quiz/quiz_model.py --fake` passes: the scripted reference passes with no rejected finding and every control ends exactly as declared.
* No finding or conclusion is ever accepted with an id the run did not issue (tested on every day's build).
* A real qwen3:4b baseline is recorded in `results/` before day 7 (week 03 retro).
