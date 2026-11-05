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
