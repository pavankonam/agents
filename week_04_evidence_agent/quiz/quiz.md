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
