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

**Decision:** `scripted.py` holds the reference run for `checkout_latency` and four controls (six from day 2, see D17) with their expected outcome: text only (fail, no_conclusion), conclude citing an invented id (fail, no_conclusion), a rejected finding then the reference (pass, 1 rejected finding), blame the red herring search deploy with real evidence (fail, concluded). Tests and `quiz_model.py --fake` both use them.
**Why:** One definition means the quiz and the tests cannot disagree about what a control should score. The wrong service control shows that real citations alone are not enough to pass.

## D11. A real baseline path from day 1 (2026-11-05)

**Decision:** `quiz_model.py --record PATH` and `run --record PATH` append one JSON report per run, and the README gives the one command that writes `results/qwen3_4b.jsonl` on the Mac. `results/fake_reference.jsonl` is the scripted run, committed as a format example.
**Why:** The week 01, 02 and 03 retros all said the real model numbers came too late. The automation's shell still cannot reach Ollama (checked today: `localhost:11434` refuses, no `ollama` binary), so the best it can do is make the real run a single command that Pavan can run any day this week.
**Alternatives:** Wait for day 7 (repeats the mistake three weeks running).

## D12. LLM client copied from week 03, env var `EVIDENCE_AGENT_MODEL`, default `qwen3:4b` (2026-11-05)

**Decision:** Copy `llm.py` with only the env var renamed.
**Why:** One folder, one project (week 03 D6). Same model as last week so results can be compared.

## D13. Claims are checked through an optional structured `check`, not by reading the claim text (2026-11-06)

**Decision:** `report_finding` takes an optional `check` object `{service, field, op, value, at?}`. Code compares it with the rows the finding cites and gives the finding a support status: `supported`, `contradicted`, `unsupported`, `invalid` or `unchecked` (no check given). Reports and JSON carry the status per finding and a count per status.
**Why:** The day 1 gap was a finding that cites real ids that do not say what the claim says. Parsing free text claims ("p95 went way up") is the brittle keyword matching D8 already ruled out. A small structured check is something a 4B model can fill in from the row it just read, and it makes support a deterministic comparison, in the spirit of the AWS advice to pair agents with plain Python checks.
**Alternatives:** An LLM judge for support (a second model to trust, and not deterministic), making `check` required (a small model that cannot fill it in would never record any finding; the rate of unchecked findings is itself a useful number), free text plus regex for numbers (cannot tell which row or time a number belongs to).

## D14. Only cited rows count, and only after the ids are valid (2026-11-06)

**Decision:** `check_support` looks at the cited rows only, never at the rest of the scenario. If any cited id is unknown the check is not judged (status `unchecked`) and the finding is rejected for the citation alone.
**Why:** The question is "does the evidence the model chose back what it says", so a claim that happens to be true but cites the wrong rows must not pass. Judging a check on a partly invented citation list would mix two failures in one status and make the counts hard to read.
**Alternatives:** Check the claim against all scenario rows (would accept a true claim with irrelevant citations, which is exactly what this day is meant to catch), judge on the valid subset of ids (hides the invented id behind a support status).

## D15. Semantics: "some relevant cited row holds"; contradicted vs unsupported (2026-11-06)

**Decision:** A cited row is relevant when its service matches, it has the field (metric name for metric rows, `level`/`message` for logs, `version`/`note` for deploys) and, if `at` is given, its time matches. `supported` if at least one relevant row satisfies the check, `contradicted` if relevant rows exist and none does, `unsupported` if no cited row is relevant. `>`, `>=`, `<`, `<=` need a number (a numeric string is converted); `==` and `contains` compare text case insensitively. Common spelled out operators (`gt`, `lte`, `eq`, `=`, `equals`) are accepted as aliases.
**Why:** "At some cited time" without `at` matches how people write findings ("error rate reached 0.4") and `at` pins a claim to one moment when it matters. Splitting contradicted from unsupported separates a wrong reading of the right rows from citing the wrong rows, two different model mistakes. Aliases cost nothing and avoid rejecting a correct claim over spelling.
**Alternatives:** "All relevant rows hold" (a claim about a spike would be contradicted by the calm rows the model cited for contrast, as in the reference's 230 to 2900 finding), time ranges (`from`/`to`; deferred until a scenario needs one).

## D16. Anything but supported rejects the finding, with the rows named (2026-11-06)

**Decision:** A finding whose check is contradicted, unsupported or invalid is rejected like an invalid citation (kept with `accepted=False`, D7) and the error spells out why, for example `claim contradicted: cited rows contradict checkout p95_latency_ms > 2000 at 14:00: ev_006 has 230`.
**Why:** The PRD asked that such findings are "no longer accepted silently"; rejecting them with the actual values lets the model fix either the claim or the citation on the next turn, the same feedback loop as day 1.
**Alternatives:** Accept and only flag (the conclusion could still rest on a contradicted finding with no pressure to fix it), end the run (too harsh for one misread number).

## D17. Reference carries checks; two new controls (2026-11-06)

**Decision:** Every reference finding now has a check that its cited rows support. Two controls are added: `contradicted_claim` (claims checkout p95 was above 2s at 14:00 citing the 230 ms row, then the reference) and `irrelevant_citation` (a db cpu claim citing the payments deploy row, then the reference). Both pass with one rejected finding. `CONTROLS` entries gain a fifth field, the expected support status of each finding in order, and `quiz_model.py --fake` checks it and that every reference finding is supported.
**Why:** The controls prove both new rejection paths through the whole agent loop, not just in unit tests, and the per finding status tuple catches a regression that keeps counts right but labels wrong.
**Alternatives:** Controls that end without the reference (would only test failure, not that the model can recover after the rejection).

## D18. Two scenarios built around the two classic wrong answers (2026-11-07)

**Decision:** `config_push`: a gateway config push cuts the upstream timeout from 30 s to 300 ms while api p95 stays near 440 ms, so a third of requests get 503; the red herring is a worker CPU spike to 96% at 09:08 from a nightly reindex, two minutes before the first error. `dependency_outage`: an external `email_vendor` becomes unreachable at 16:18 and signups fail from 16:20; the first deploy of the afternoon (web, page copy, 16:10) is innocent and a second deploy (signup, 16:30) lands after the failures began. The question for this scenario even says "there was a deploy shortly before".
**Why:** The PRD asked for a misleading CPU spike and an innocent first deploy, the two shortcuts an investigator (human or model) most often takes: blame the loudest metric, or blame the most recent change. In both scenarios the red herring rows are real and a claim about them is *supported*, so only the conclusion's service tells the runs apart. The root cause of `dependency_outage` has no deploy at all, which checkout_latency could not test.
**Alternatives:** Random noise rows (day 6 adds seeded noise; today's scenarios should have one deliberate trap each), a scenario where the cause is in the db (too close to checkout_latency's pool story).

## D19. Ground truth now marks the cause rows, and the ledger keeps each record's key (2026-11-07)

**Decision:** `Scenario` gains `cause`, the indices of the rows that show the cause (deploy, error logs, failing metric of the root cause service), set by wrapping rows in `_Cause(...)` when the scenario is built. `Evidence` gains `key`, the record's index in the scenario, so grading can map a cited id back to a ground truth row.
**Why:** "Cited evidence covers the cause" needs to know which rows are cause rows. Marking them inline next to the data keeps the marks from drifting when rows are added, and the ledger already had the key when it issued the id.
**Alternatives:** Hand written index lists (break silently when a row is inserted), "any row of the root cause service" (a calm 13:55 payments metric would count as evidence of the cause).

## D20. The rubric: 40 root cause, 30 cause evidence, 20 no contradicted claim, 10 efficiency (2026-11-07)

**Decision:** `grading.py` scores each run out of 100: root cause service right (40), the conclusion cites at least one cause row (30), no finding was `contradicted`, accepted or rejected (20), steps within `reference_steps + 2`, then 2 points off per extra step down to 0 (10). Each criterion keeps its points, max and a one line detail. `Report` carries the grade, the JSON has `score` and `grade`, and `report_lines` prints `score N/100 (...)`. `passed` is unchanged (D8).
**Why:** Pass/fail hides the difference between a model that names the right service for the wrong reasons and one that proves it. Cause evidence is checked on the conclusion only, because the conclusion is what an on call engineer reads. A contradicted finding counts even when it was rejected and fixed, because misreading a number is the mistake this week is measuring. `unsupported` is not penalised (the PRD named contradicted; an irrelevant citation that was rejected and replaced cost nothing in the end). Efficiency is small and has slack so a model that double checks is not punished for one extra query.
**Alternatives:** Score from the summary text (D8 ruled that out), equal weights (efficiency would matter as much as the right answer), penalising `unsupported` too (left for day 6 when real model numbers show how common it is).

## D21. No conclusion, no points (2026-11-07)

**Decision:** A run without a conclusion scores 0 on every criterion, including "no contradicted claim" and efficiency.
**Why:** Otherwise a model that answers in plain text after one step would get 30 points for doing nothing wrong and nothing quickly.
**Alternatives:** Give efficiency and no_contradicted anyway (rewards giving up early).

## D22. Controls per scenario and a declared score for every control (2026-11-07)

**Decision:** `CONTROL_SCENARIO` maps a control to its scenario (default `checkout_latency`) and `CONTROL_SCORES` declares the score each control must get. Three new controls: `blame_cpu_spike` (config_push, a supported finding about the CPU spike, then conclude worker: fail, 30), `blame_first_deploy` (dependency_outage, conclude web citing its deploy: fail, 30) and `cause_not_cited` (dependency_outage, right service but citing only a signup row: pass, 70). `quiz_model.py --fake` checks every reference scores 100 and every control's score, and prints the score per scenario and the mean.
**Why:** `cause_not_cited` is the case the rubric exists for: it passes and still loses 30 points. Declaring scores next to the controls keeps the quiz and the tests from disagreeing, as D10 did for outcomes. A separate mapping leaves the five field `CONTROLS` tuples unchanged.
**Alternatives:** Add the scenario and score as fields six and seven of each tuple (every unpacking in tests and the quiz would change for no gain).

## D23. A query budget over the three row reading tools (2026-11-08)

**Decision:** `max_queries` (default 8, CLI `--max-queries`) counts calls to `search_logs`, `get_metric` and `list_deploys` that pass validation and the window rule. `list_services` is free. `get_metric` without a metric name still costs a query. When the budget is used up the query is refused with `query budget of N used up; report findings or conclude with the evidence you already have`, the step counts as refused and the refusal is audited. Findings and `conclude` never cost budget. The system prompt states the budget.
**Why:** Honeycomb's AI SRE news framed bounds as something the team sets per investigation; a query budget is the simplest one, and it is separate from the step limit so a model can spend steps fixing rejected findings without being able to keep fishing in the data. Counting by tool name keeps the rule one line long. Refused queries do not spend the budget, so a malformed or out of window query is not punished twice.
**Alternatives:** Count rows returned (punishes a broad but legitimate first query), count `list_services` too (it reveals no data), reuse `max_steps` (cannot tell querying from reporting).

## D24. The incident window: since/until on every query tool, refused outside it (2026-11-08)

**Decision:** Each scenario has a `window` (`checkout_latency` 13:45 to 14:15, `config_push` 08:55 to 09:20, `dependency_outage` 15:55 to 16:35) containing all its rows. Query tools accept optional `since` and `until` (HH:MM); a value that is malformed, outside the window, or `since` after `until` is refused and audited as `time_window`; inside the window they filter the rows shown. Omitting both means the whole window.
**Why:** The PRD asked for a time window rule. A real backend would happily return last week's data; a bounded investigator should not read outside what the operator scoped. Making since/until filters also gives the model a real reason to use them (narrowing to the minutes around the spike), so the rule is not just a trap.
**Alternatives:** Silently clamp to the window (the model would not learn its query was out of scope, and the audit would show nothing), put rows outside the window in the scenarios and hide them (would change every evidence id and every scripted run for no new lesson).

## D25. A kill switch checked before every model turn and every tool call (2026-11-08)

**Decision:** `KillSwitch.trigger(by, reason)` needs both a who and a why, is thread safe and keeps the first trip. `run_investigation(kill_switch=...)` checks it before each model turn, and `Investigation.call` checks it before each tool call; a tripped switch ends the run as `killed`, the pending call never runs and is not a step. `FileKillSwitch(path)` trips when a file appears, reading `who: why` from its first line (else `operator` and the line), and the CLI exposes it as `--kill-file`. The control `operator_kill` trips the switch while the model works on turn 3 (`KillingClient`), so the call that turn returned is dropped.
**Why:** CrowdStrike's kill switch news stressed that the stop must come from outside the agent and be on the record with who and why. Checking before tool calls (not only between turns) matters because one model turn can carry several calls. A file is the simplest out of loop signal for a CLI on a laptop: another terminal can stop the run without signals or a server.
**Alternatives:** POSIX signals (no clean way to carry who and why, and awkward on macOS terminals), a socket or HTTP endpoint (a server for one boolean), checking only between turns (a batch of calls would still run after the stop).

## D26. One audited stop per run; refusals by bounds are audited too (2026-11-08)

**Decision:** Every end of a run goes through `Investigation._end(reason, actor, why)`, which writes one `AuditEntry(step, event="stop", rule, actor, reason)`: `concluded` and `no_conclusion` by `agent`, `step_limit` and `turn_limit` by `system`, `killed` by the operator's name. Budget and window refusals add `event="refused"` entries by `system`. Citation rejections are not audited (they are already in the findings and steps). `Report` carries `audit`, `queries_used` and `max_queries`; `report_lines` prints `audit:` lines and `N/M queries`; CLI `--audit PATH` appends each entry as a JSON line with scenario and model.
**Why:** The PRD says every stop lands in the audit log with who and why; one choke point makes "exactly one stop, last in the log" a testable invariant over every control and reference. Keeping citation problems out of the audit log keeps it about bounds and stops, the operator's view, instead of duplicating the findings list.
**Alternatives:** Audit every step (noise; the steps are already in the report), log stops with Python `logging` (not in the report or JSON, so not testable or recordable).

## D27. Three bounded controls with declared options and audit logs (2026-11-08)

**Decision:** `over_budget` (budget 2: the third query is refused, two supported findings and a conclusion on what it has; passes, score 100), `out_of_window` (a payments search from 12:00 is refused, then the reference; passes, 8 steps, score 100) and `operator_kill` (the reference, killed by `oncall:pavan` during turn 3; fails, 2 steps, score 0). `CONTROL_OPTIONS` holds their run options, `CONTROL_AUDIT` their exact audit log as (step, event, rule, actor); every other control must leave one stop entry matching its end reason. `make_control(name)` builds the client and options, used by tests and `quiz_model.py --fake`, which now checks every audit log (15 checks).
**Why:** The bounds must be proven through the whole agent loop like the citation rules were. `over_budget` shows that a budget refusal is recoverable when the model concludes on what it already saw, and its score shows the rubric does not punish a bounded run. Declaring audit logs next to the controls follows D10 and D22.
**Alternatives:** Grade bounds in the rubric (a refusal is the system working, not the model failing; left for day 6 if real runs show models looping on refused queries).

## D28. Memory stores only accepted, supported findings, with the rows that backed them (2026-11-09)

**Decision:** `memory.py` `FindingMemory.remember` stores a finding only when it was accepted and its check came back `supported`. The entry holds the scenario name, the claim, the parsed check and the backing rows (`support_ids`, not every cited row) as plain record dicts. A finding with the same check (same `describe(check)`) on the same scenario replaces the older entry. Conclusions are never stored. The store is a JSON file `{"version": 1, "entries": [...]}`, written through a temp file and `os.replace`.
**Why:** The PRD said verified findings. Only a finding with a check can be verified again later; an unchecked finding has nothing for code to re-run, so storing it would bring back exactly the unverifiable text this week is trying to keep out. Storing backing rows only keeps the memory tight: the 14:00 checkout row that the reference cites for contrast is not evidence for "above 2000 at 14:05". Not storing conclusions keeps memory from turning into "it was payments last time", which is the shortcut the red herring scenarios punish.
**Alternatives:** Store every accepted finding (unchecked ones could never be re-checked), store the conclusion too (anchors the next run on an old answer), a SQLite store (one small JSON file is enough and readable by hand).

## D29. Re-check by row identity, then re-run the check on the current values (2026-11-09)

**Decision:** Before a run each stored row is looked up in the current scenario by its identity: kind, time, service and, for metrics, the metric name, but not the value. A row with no match drops the finding (`row no longer in the data: ...`). Then the stored check runs again, through the same `check_rows` code as live findings (`support.check_support` now calls it), on the rows found now. Anything but `supported` drops the finding with the reason, for example `claim now contradicted: current rows contradict checkout p95_latency_ms > 2000 at 14:00: 14:00 checkout p95_latency_ms=230 has 230`. Only the rows that back the check now are recalled.
**Why:** Matching on the full row would make the re-check trivial: an identical row always satisfies the same check, and a changed value would look like a missing row instead of a contradicted claim. Matching on identity separates the two ways memory goes stale (the row is gone, or it now says something else) and reuses the verifier the model already faces, so a remembered claim is held to the same rule as a new one.
**Alternatives:** Trust memory and skip the re-check (the failure the PRD is about), compare a hash of the scenario (drops everything on any change, even unrelated rows).

## D30. Dropped findings are forgotten; other scenarios' entries are left alone (2026-11-09)

**Decision:** `recall(scenario)` re-checks only that scenario's entries. Kept entries stay, dropped entries are removed from the store, and the CLI saves the file after the run. Each re-check is a `Recalled(claim, status, reason, keys, ids)` in `Report.recall`, printed as `recall: kept ...` or `recall: dropped ...: reason` and counted in a `memory: recalled K, dropped D, stored N` line, and included in `--json`.
**Why:** A finding the data no longer supports would otherwise be re-checked and dropped on every run forever. The report keeps the reason, so forgetting loses nothing an operator needs.
**Alternatives:** Keep dropped entries marked stale (more state for no use until data can change back, which synthetic scenarios do not do).

## D31. Recalled rows enter the ledger before the first turn and cost no query (2026-11-09)

**Decision:** `Investigation.preload(recalled)` issues ids for the backing rows of kept findings, in memory order, with tool `recall` and step 0, before any step (calling it later is an error). The model sees them appended to the question: each claim and its rows as `[ev_001] 14:02 payments deploy ...`, plus how many entries were dropped and that it should not rely on them. Recall is not a tool call, is not a step and spends no query budget.
**Why:** Recalled rows have been shown to the model, so they are citable under the ledger rule (D4, D5) and grading maps them to cause rows as usual. Charging budget for them would make memory pointless under a tight budget; the point of remembering verified work is to skip repeating those queries. Telling the model how many entries were dropped gives it a reason not to trust anything it half remembers from its own context.
**Alternatives:** A `recall` tool the model calls (the PRD says the next run can recall them; a tool would let a model skip the re-check story or spend a step on it), recalled findings as accepted findings of the new run (they would count as findings the model never made and inflate support counts).

## D32. Two memory controls and declared recall counts (2026-11-09)

**Decision:** `recall_reuse` runs `checkout_latency` with the store the reference run leaves (`reference_memory()`): the three findings are kept as `ev_001` to `ev_004`, one query adds the payments error rate, one new supported finding, and the conclusion cites recalled and new ids; it passes in 3 steps with score 100. `recall_stale` is the same with two entries written against older data placed first (`STALE_ENTRIES`: checkout p95 2400 at 14:00, now 230; a 14:01 payments deploy that no longer exists): both are dropped, the three good ones still get `ev_001` to `ev_004`. `CONTROL_RECALL` declares (kept, dropped) per control, others (0, 0), and `quiz_model.py --fake` checks it (17 checks).
**Why:** The controls prove the memory path through the whole agent loop: recalled ids are citable, they reach the cause rows the rubric looks for, and dropped entries take no ids and do not shift the kept ones. Putting the stale entries first is what tests that.
**Alternatives:** A third scenario variant with changed data for the stale control (the unit tests already replace single records with `dataclasses.replace`; a stored entry from older data is the realistic case).
