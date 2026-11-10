# Self Quiz: Evidence Agent

Each day the automation answers these from memory, then checks the answer against the code and docs. A FAIL means either the answer or the docs were wrong, and it gets fixed the same day.

## Day 1 (2026-11-05)

**Q1. The model's first call is `report_finding` citing `ev_001`. What happens, and is the finding stored?**
Answer: Refused. The error is `finding rejected: unknown evidence id(s): ev_001 (never returned by a tool in this run)`, because no query has issued any id yet. The finding is stored with `accepted=False` and that problem (D7), and the step counts as refused.
Verified: `_citation_problems` uses `EvidenceLedger.unknown`; `_t_report_finding` appends the `Finding` before returning the error. Test `test_finding_with_invented_id_is_rejected_and_kept`. **PASS**

**Q2. `search_logs(service="payments", level="ERROR")` is called, then `search_logs(service="payments", contains="POOL")`. Which ids does the second call show?**
Answer: `ev_001` and `ev_002` again. The two pool errors are the only payments ERROR lines and the same records match the case insensitive "POOL" search, and a record keeps its first id. The ledger still holds 2 ids.
Verified: `EvidenceLedger.issue` returns the stored id for a known key; `contains` is lowercased on both sides. Test `test_query_lines_carry_ids_and_same_record_keeps_id`. **PASS**

**Q3. A search matches 13 log lines. How many evidence ids are issued, and can the model cite the 11th row?**
Answer: 10 ids. Only the first 10 lines are shown, followed by `(3 more not shown; ...)`; hidden rows get no id, so citing `ev_011` is rejected (D5).
Verified: `_rows` slices `matches[:limit]` before issuing ids; `search_logs` passes `limit=DEFAULT_LIMIT` (10). Test `test_hidden_rows_get_no_id`. **PASS**

**Q4. The model runs the reference queries, then concludes `search` citing the real id of the search deploy. Passed? End reason?**
Answer: Not passed, end reason `concluded`. The citation is valid so the conclusion is accepted and ends the run, but `root_cause_correct` is False because the ground truth is `payments` (D8).
Verified: `control_wrong_service` in `scripted.py` expects `(False, "concluded", 0)`; ran `quiz_model.py --fake` on 2026-11-05: `control wrong_service: OK passed=False end=concluded`. **PASS**

**Q5. The model calls `conclude` with an invented id, then answers in text. What is the end reason and how many rejected findings are reported?**
Answer: `no_conclusion` with 0 rejected findings. A rejected conclusion is only a refused step (`refused_steps` 1), not a finding, and the text reply then ends the run (D6, D7).
Verified: `_t_conclude` returns an error without storing anything; `run_investigation` calls `finish("no_conclusion")` on a reply without tool calls. Control `invented_id` expects `(False, "no_conclusion", 0)`. **PASS**

Day 1 result: 5/5 PASS.

## Day 2 (2026-11-06)

**Q6. After the reference queries, the model reports "checkout p95 was above 2s at 14:00" citing `ev_006` with check `{checkout, p95_latency_ms, >, 2000, at 14:00}`. What happens?**
Answer: Rejected as `contradicted`. `ev_006` is the checkout p95 row at 14:00 with value 230, which is relevant (same service, metric and time) but does not hold. The error is `finding rejected: claim contradicted: cited rows contradict checkout p95_latency_ms > 2000 at 14:00: ev_006 has 230`. The finding is kept with `accepted=False` and `support="contradicted"`.
Verified: `check_support` collects relevant rows and returns `CONTRADICTED` when none holds; `_t_report_finding` appends `claim {status}: {reason}`. Control `contradicted_claim` expects `(True, "concluded", 1, (C, S, S, S))`; `quiz_model.py --fake` on 2026-11-06: `control contradicted_claim: OK`. Test `test_contradicted_finding_is_rejected_with_the_rows`. **PASS**

**Q7. A finding cites `ev_003` and `ev_099` (never issued) with a valid check. What is its support status and why?**
Answer: `unchecked`. The unknown id rejects the finding on its citation, and support is only judged when every id is real (D14), so the only problem is the unknown id. The parsed check is still stored on the finding.
Verified: `_t_report_finding` calls `check_support` only `if not cite_problems`; test `test_check_is_not_judged_on_invented_ids` asserts the exact error and `support == "unchecked"`. **PASS**

**Q8. Check `{checkout, p95_latency_ms, >, 2000}` (no `at`) citing the 14:00 row (230) and the 14:05 row (2900). Supported or contradicted? Which ids are the backing ids?**
Answer: Supported, because without `at` one relevant cited row that holds is enough (D15). Backing ids: only the 2900 row; the 230 row is relevant but does not hold, so it is not listed.
Verified: `check_support` returns `SupportResult(SUPPORTED, "", backing)` where `backing` keeps only rows where `holds` is true; the reference's third finding (ev_006, ev_007 with at 14:05) reports `support_ids == ["ev_007"]` in `test_reference_findings_all_supported_and_counted_in_json`, and `test_check_support_without_at_needs_one_backing_row` covers the no `at` case. **PASS**

**Q9. The model sends `"op": "gt", "value": "2000"`. Is the check valid?**
Answer: Yes. `gt` is an alias for `>`, and for numeric operators a numeric string is converted to a float (2000.0). `"value": "high"` with `>` would be `invalid` with `check op > needs a number, got 'high'`.
Verified: `OP_ALIASES` and the `float(value)` branch in `parse_check`; tests `test_parse_check_normalises_aliases_and_numbers` and `test_parse_check_errors`. **PASS**

Day 2 result: 4/4 PASS (9/9 total).

## Day 3 (2026-11-07)

**Q10. On `dependency_outage` the model searches signup ERROR logs, then concludes `email_vendor` citing only `ev_001`. Passed? Score?**
Answer: Passed (right service, valid citation, D8) but scores 70: root_cause 40, cause_evidence 0 because `ev_001` is a signup log row and none of the scenario's cause rows (all on `email_vendor`), no_contradicted 20, efficiency 10 (2 steps against a reference of 8).
Verified: `grade` maps each cited id through `ledger.get(e).key` into `scenario.cause`; `_DEPENDENCY_CAUSE` holds only `email_vendor` rows (checked by `test_records_time_ordered_and_cause_rows_on_root_cause_service`). Control `cause_not_cited` declares 70 in `CONTROL_SCORES`; `quiz_model.py --fake` on 2026-11-07: `control cause_not_cited (dependency_outage): OK passed=True ... score=70`. **PASS**

**Q11. The model answers in plain text after one query. What does it score on no_contradicted and efficiency?**
Answer: 0 on both, and 0 overall: a run without a conclusion earns nothing (D21).
Verified: `grade` returns early with every criterion at 0 and detail `no conclusion` when `conclusion is None`; test `test_no_conclusion_scores_zero_on_every_criterion`; control `text_only` scores 0. **PASS**

**Q12. `contradicted_claim` misreads a row, gets the finding rejected, then follows the reference. It passes; what does it score and why?**
Answer: 80. It loses the 20 for no_contradicted because a contradicted finding counts even when rejected (D20). Efficiency stays at 10: 8 steps against a reference of 7 is within the slack of 2.
Verified: `grade` counts `CONTRADICTED` over the support status of all findings, not only accepted ones; `efficiency_points(8, 7)` is 10 since 8 is within 7 + 2. `test_contradicted_finding_costs_20_even_when_rejected`; `CONTROL_SCORES["contradicted_claim"] == 80` and the quiz printed `score=80`. **PASS**

**Q13. On `config_push`, the model reports "worker cpu hit 96% at 09:08" citing the real 09:08 row with a check `worker cpu_pct > 90 at 09:08`. Is the finding accepted? Does the run pass?**
Answer: The finding is accepted as `supported`, because the cited row really holds 96. The run still fails when it concludes `worker`: the root cause is `gateway`. Score 30 (no_contradicted 20 and efficiency 10 only). A true claim about a red herring is not evidence of the cause (D18).
Verified: control `blame_cpu_spike` expects `(False, "concluded", 0, (S,))` and score 30; quiz output on 2026-11-07 `control blame_cpu_spike (config_push): OK passed=False ... support=supported score=30`. **PASS**

Day 3 result: 4/4 PASS (13/13 total).


## Day 4 (2026-11-08)

**Q14. With `max_queries=2` the model runs `list_deploys`, a payments ERROR search, then `get_metric(checkout, p95_latency_ms)`. What happens to the third call, and what is in the audit log after it concludes on the first two queries?**
Answer: Refused with `query budget of 2 used up; report findings or conclude with the evidence you already have`. It is step 3, counts as a refused step, issues no ids and `queries_used` stays 2. The audit log is `(3, refused, query_budget, system)` then `(6, stop, concluded, agent)`; the run passes with score 100.
Verified: `_bound_problem` checks `queries_used >= max_queries` before the window and appends the refused entry; control `over_budget` declares exactly that audit in `CONTROL_AUDIT`; `quiz_model.py --fake` on 2026-11-08: `control over_budget (checkout_latency): OK ... score=100 audit=ok`. **PASS**

**Q15. On `checkout_latency` the first call is `search_logs(service="payments", level="ERROR", since="12:00")`. Refused? Does it spend budget? What would `since="14:05", until="14:10"` on the checkout p95 metric show?**
Answer: Refused as `time_window`: `since 12:00 is outside the incident window 13:45 to 14:15; queries outside the window are refused`. It spends no budget (budget is only spent after both checks pass). The narrowed metric query shows only the 14:05 (2900) and 14:10 (3100) rows.
Verified: `window_problem` returns that text; `queries_used += 1` happens only after it returns ""; `_rows` filters on `since <= ts <= until`. Tests `test_window_refusal_spends_no_budget_and_since_until_filter_rows` and `test_window_problem`; control `out_of_window` audit `(1, refused, time_window, system)`. **PASS**

**Q16. The operator trips the kill switch while the model is producing its third turn of the reference run. Does the tool call of that turn run? End reason, steps, score, audit?**
Answer: No. `Investigation.call` checks the switch first, so the call is dropped and is not a step. End `killed`, 2 steps, 4 evidence ids, 2 of 8 queries, no conclusion, score 0. Audit: one entry `step 2 stop killed by oncall:pavan: incident handed to a human responder`.
Verified: `call` returns `investigation stopped by ...` with `done=True` before appending a `StepLog`; `KillingClient` triggers after its third `chat`; `test_operator_kill_control_report` asserts the line and JSON; quiz output `control operator_kill ... end=killed ... score=0 audit=ok`. **PASS**

**Q17. Which tools spend the query budget? Does `get_metric(service="checkout")` without a metric name cost one?**
Answer: `search_logs`, `get_metric` and `list_deploys` (`QUERY_TOOLS`). `list_services`, `report_finding` and `conclude` are free. `get_metric` without a metric only lists names but still costs a query, because the budget counts by tool name (D23).
Verified: `QUERY_TOOLS` in `bounds.py`; `call` runs `_bound_problem` for any `name in QUERY_TOOLS` after validation; `test_query_budget_refuses_and_audits_without_spending` shows `list_services` succeeding with the budget used up. **PASS**

Day 4 result: 4/4 PASS (17/17 total).


## Day 5 (2026-11-09)

**Q18. After the checkout reference run with a memory, which findings are stored, and which rows does the third one keep?**
Answer: All three, because each was accepted and its check was `supported`. The third ("checkout p95 went from 230ms to 2900ms at 14:05") cited the 14:00 and 14:05 rows, but only the backing row is stored: `14:05 checkout p95_latency_ms=2900`. A finding without a check, or a rejected one, is never stored (D28).
Verified: `FindingMemory.remember` skips anything not `accepted and support == SUPPORTED and check and support_ids` and stores `ledger.get(i).record.to_dict()` for `support_ids` only; running `reference_memory()` on 2026-11-09 printed the three claims and `[{'kind': 'metric', 'ts': '14:05', 'service': 'checkout', 'data': {'metric': 'p95_latency_ms', 'value': 2900}}]` for the third; an unchecked accepted finding gave `remember(...) == 0`. Tests `test_remember_stores_supported_findings_with_backing_rows_only`, `test_unchecked_and_rejected_findings_are_not_stored`. **PASS**

**Q19. The data changes: checkout p95 at 14:05 now reads 1500. What happens to the remembered checkout finding on the next run, and is it still in the store afterwards?**
Answer: The row is still found (same kind, time, service and metric; identity ignores the value), the check `> 2000 at 14:05` is re-run on 1500 and comes back contradicted, so the finding is dropped with `claim now contradicted: current rows contradict checkout p95_latency_ms > 2000 at 14:05: 14:05 checkout p95_latency_ms=1500 has 1500`. It is removed from the store; the other two are kept (D29, D30).
Verified: `identity()` excludes the value; `recheck` runs `check_rows(..., what="current")` and returns `DROPPED` for anything but supported; `recall` keeps only `KEPT` entries. Running it with that record replaced printed `[('kept', ''), ('kept', ''), ('dropped', 'claim now contradicted: ... 14:05 checkout p95_latency_ms=1500 has 1500')]` and 2 entries left. **PASS**

**Q20. In `recall_stale`, two stale entries come first. Which evidence ids do the three good findings get, does recall spend query budget, and how many steps and what score does the run end with?**
Answer: The dropped entries issue no ids, so the kept findings still get `ev_001` (payments deploy), `ev_002` and `ev_003` (pool exhausted logs) and `ev_004` (checkout p95 14:05). Recall is not a step and spends no query: the run uses 1 of 8 queries (the payments error rate, `ev_005` to `ev_008`), 3 steps, passes with score 100 and recall counts 3 kept, 2 dropped (D31, D32).
Verified: `preload` only calls `ledger.issue` for `KEPT` entries with tool `recall` and step 0 and refuses to run after a step; `quiz_model.py --fake` on 2026-11-09: `control recall_stale (checkout_latency): OK passed=True end=concluded rejected=0 support=supported score=100 audit=ok recall=3/2`; `test_stale_entries_dropped_and_model_told` asserts the ids. **PASS**

**Q21. With a memory holding the three reference findings, the model's first call is `conclude(payments, evidence_ids=["ev_005"])`. Accepted?**
Answer: No. Recall issued only `ev_001` to `ev_004`, so `ev_005` was never issued in this run and the conclusion is rejected as an unknown id; recalled ids are citable, invented ones still are not. A second conclude citing `ev_001` passes with 0 queries used (D4, D31).
Verified: `test_recalled_ids_cost_no_query_and_are_citable_but_invented_ids_are_not` asserts 1 refused step, passed, `queries_used == 0` and `evidence_issued == 4`. **PASS**

Day 5 result: 4/4 PASS (21/21 total).


## Day 6 (2026-11-10)

**Q22. What does `variant(checkout_latency, 1)` change, and which id does `list_deploys` give the payments v2.3.1 deploy on it?**
Answer: Three INFO noise rows inside 13:45 to 14:15 (13:49 checkout `metrics flushed`, 13:59 search `gc pause 8ms`, 14:01 db `health check ok`), a seeded order among rows that share a minute, and `id_seed=1`, so the ledger draws ids in a seeded order. The cause rows and root cause are unchanged. `list_deploys` shows `[ev_199]` for the search deploy and `[ev_937]` for the payments deploy, instead of `ev_001` and `ev_002`.
Verified: printed the noise rows and the `list_deploys` output on 2026-11-10; `test_variants_keep_the_incident_and_are_reproducible` checks the noise is INFO, inside the window, time ordered and that the cause rows are the same lines. **PASS**

**Q23. The checkout reference, with its hard coded ids, is played straight on seed 1. How does it end, how many rejected citations, and what does `ReplayClient` do differently?**
Answer: It ends `no_conclusion` with score 0: its three findings and its conclusion cite ids like `ev_002` that this run never issued, so 4 citing calls are refused, and then the script runs out. `ReplayClient` learns which row each script id named on the base scenario, reads the `[ev_NNN] line` rows this run's tools returned, and rewrites the ids by row, so the run passes with score 100 citing `ev_937, ev_349, ev_169`. Invented ids are passed through and still rejected.
Verified: `test_memorised_ids_fail_on_a_variant_but_replay_passes` asserts `no_conclusion` and `rejected_citations == 4`, then pass and 100 with different ids; `test_replay_keeps_invented_ids_invented`; `quiz_model.py --fake`: `eval memorised ids (3 seeds): OK 3/9 passed, failure kinds {'no_conclusion': 6}`. **PASS**

**Q24. An eval of checkout over 3 seeds passes 2 of 3 runs. Exit code with the default `--min-pass-rate`, and with 0.6? What does `--json --markdown` give?**
Answer: Default 1.0: exit 1. With 0.6: 2/3 = 0.67 is at least 0.6, exit 0 (0.7 would give 1). `--json` with `--markdown` is a usage error, exit 2, because the two are a mutually exclusive group.
Verified: ran `run_eval` with seed 2 replaced by `control_wrong_service` on 2026-11-10: exit 0 at 0.6, 1 at 0.7, summary `2/3 passed (67%)`; that failed run is `no_conclusion` (its scripted ids are not issued on the variant), not `wrong_root_cause`. `test_cli_eval_usage_and_ollama_codes` asserts exit 2 for `--json --markdown`. **PASS**

**Q25. Why does the variant need a seeded ledger order? Would noise rows and same minute reordering alone have changed the ids the references cite?**
Answer: No. The references query `search_logs` with `level=ERROR`, `get_metric` by name and `list_deploys`; INFO noise never shows up in those, and the reordered same minute rows are not in the same result, so every cited id stayed the same and the memorised script still passed every variant. The seeded ledger order is what makes an id meaningless outside its run (D34).
Verified: with `id_seed=None` forced on seeds 1 to 3 of all three scenarios, the plain reference passed 9/9 on 2026-11-10; with the seed set it fails all 6 variants. **PASS**

Day 6 result: 4/4 PASS (25/25 total).
