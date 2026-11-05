# Decision Log: Evidence Agent

Each entry: what was decided, why, and what else was considered. New entries are appended at the bottom.

## D1. Project topic: an incident investigator whose claims must cite what it saw (2026-11-05)

**Decision:** Build an incident investigation agent over synthetic telemetry where every finding cites evidence ids, checked by code.
**Why:** The week's news put AI SRE agents (Honeycomb), kill switches (CrowdStrike) and deterministic checks beside agents (AWS) next to each other, and the common advice was "require evidence links". It is also the next step in the series: week 03 checked what an agent **did** by its final state; an investigator does nothing to the world, so the only thing to check is whether what it **says** is backed by what it **retrieved**.
**Alternatives:** A message threads style context cache for long sessions (Anthropic's beta is an API feature, hard to mirror meaningfully with Ollama), an Agent Client Protocol coding agent (Android Studio news; large surface, overlaps week 01), a connect once connector hub (mostly auth plumbing, nothing local to measure).

## D2. Telemetry as small typed records: log, metric, deploy (2026-11-05)

**Decision:** `Record(kind, ts, service, data)` with three kinds and `HH:MM` timestamps on one day. A `Scenario` holds the records, the question and the ground truth root cause service.
**Why:** Three kinds are enough for the classic incident shape (a deploy, then errors, then a symptom upstream) and each prints as one readable line. Same day `HH:MM` strings sort as time without a date library.
**Alternatives:** Real OpenTelemetry spans (much bigger schema, nothing extra to learn on day 1), CSV fixtures (one more file format to load).

## D3. Everything in memory and deterministic (2026-11-05)

**Decision:** Scenarios are Python constants; tools filter them in record order.
**Why:** Tests and the quiz must run without any backend, and evidence ids must be reproducible so scripted runs can cite them.
**Alternatives:** SQLite (a query language the model could abuse, and nothing it adds yet).

## D4. An evidence ledger is the only source of citable ids (2026-11-05)

**Decision:** Every record a query tool returns gets an id `ev_NNN` in the order first seen; the same record keeps its id when returned again. `report_finding` and `conclude` reject any id the ledger did not issue in this run.
**Why:** The cheapest hallucination in a report is a made up reference. Issuing ids at retrieval time turns "is this citation real" into a set lookup. Numbering by first sight (not by record index) means ids leak nothing about records the model has not seen.
**Alternatives:** Cite by timestamp and service (ambiguous: two identical pool errors a minute apart), global record ids (the model could guess `rec_12` without querying), hashing the row text (unreadable for a small model).

## D5. Only rows actually shown get an id (2026-11-05)

**Decision:** `search_logs` shows at most 10 lines; rows past the limit are counted in a "(N more not shown)" line and get no id.
**Why:** Found while testing day 1: the first version issued ids for every match and cut the text afterwards, so the model could cite rows it was never shown. The rule is "citable means seen".
**Alternatives:** No limit (fine for 20 records, wrong once day 6 adds noise rows).

## D6. Agent loop: tool calls until conclude; text is not a conclusion (2026-11-05)

**Decision:** `run_investigation` sends the system prompt, the question and the six tools, executes tool calls in order, returns every result (or `error: ...`) as a tool message, and stops when `conclude` succeeds, the step limit is hit, the turn limit is hit, or the model replies with text only (`no_conclusion`). Calls after a successful `conclude` in the same turn are skipped.
**Why:** Same shape as weeks 01 to 03. A text answer cannot be checked, so it ends the run without a verdict instead of being parsed.
**Alternatives:** Parse the final text for a service name (brings back trusting the model's words).

## D7. Rejected findings are kept, rejected conclusions are not (2026-11-05)

**Decision:** A rejected finding is stored with `accepted=False` and its problems, and the tool returns an error so the model can try again. A rejected conclusion is a refused step only: the run continues and nothing is stored as the conclusion. `Report.refused_steps` counts every refused call.
**Why:** The rejected findings are the interesting data for this project (how often a local model invents ids), so they should be visible in the report. A conclusion is the verdict and only a valid one can end the run.
**Alternatives:** Drop rejected findings (loses the measurement), end the run on a bad conclusion (one typo ends an otherwise good investigation).

## D8. Pass is computed from ground truth, not the summary (2026-11-05)

**Decision:** `passed` = a valid conclusion exists and its `root_cause_service` equals the scenario's. The summary text is shown but not scored on day 1.
**Why:** Same principle as week 03 (D7 there): the verdict comes from checked facts. Grading the evidence itself (does it cover the cause, are claims contradicted) is day 2 and day 3 work.
**Alternatives:** Keyword match on the summary (easy to game, brittle).

## D9. CLI and exit codes (2026-11-05)

**Decision:** `list`, `check` (Ollama preflight) and `run SCENARIO [--model] [--max-steps] [--json] [--record PATH]`. Exit 0 pass, 1 fail, 2 usage, 4 Ollama not ready, the same table as week 03.
**Why:** The week 03 exit code table worked and scripts around it carry over.

## D10. Scripted reference and four controls live in the package (2026-11-05)

**Decision:** `scripted.py` holds the reference run for `checkout_latency` and four controls with their expected outcome: text only (fail, no_conclusion), conclude citing an invented id (fail, no_conclusion), a rejected finding then the reference (pass, 1 rejected finding), blame the red herring search deploy with real evidence (fail, concluded). Tests and `quiz_model.py --fake` both use them.
**Why:** One definition means the quiz and the tests cannot disagree about what a control should score. The wrong service control shows that real citations alone are not enough to pass.

## D11. A real baseline path from day 1 (2026-11-05)

**Decision:** `quiz_model.py --record PATH` and `run --record PATH` append one JSON report per run, and the README gives the one command that writes `results/qwen3_4b.jsonl` on the Mac. `results/fake_reference.jsonl` is the scripted run, committed as a format example.
**Why:** The week 01, 02 and 03 retros all said the real model numbers came too late. The automation's shell still cannot reach Ollama (checked today: `localhost:11434` refuses, no `ollama` binary), so the best it can do is make the real run a single command that Pavan can run any day this week.
**Alternatives:** Wait for day 7 (repeats the mistake three weeks running).

## D12. LLM client copied from week 03, env var `EVIDENCE_AGENT_MODEL`, default `qwen3:4b` (2026-11-05)

**Decision:** Copy `llm.py` with only the env var renamed.
**Why:** One folder, one project (week 03 D6). Same model as last week so results can be compared.
