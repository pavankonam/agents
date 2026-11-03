# Self Quiz: Agent Gym

Each day the automation answers these from memory, then checks the answer against the code and docs. A FAIL means either the answer or the docs were wrong, and it gets fixed the same day.

## Day 1 (2026-10-29)

**Q1. The model creates the right event, then replies "Booked it." without calling `submit`. What is the reward and end reason?**
Answer: Reward 1.0, end reason `no_submit`. The runner ends the episode on a text reply and the env still scores the final state (D10).
Verified: `run_episode` calls `env.finish("no_submit")` when `resp.tool_calls` is empty; `Environment.finish` runs `task.check`. Test `test_work_then_text_answer_still_scores_one`. **PASS**

**Q2. The model calls `delete_event` with `{"id": "evt_002"}`. What happens?**
Answer: The step is refused with `ok=False` and `error: unexpected argument(s) for delete_event: id`; it counts as a step (step_count 1) and no event is deleted. Unexpected arguments are checked before missing ones, so the message names `id`, not the missing `event_id`.
Verified: `validate_args` checks `extra` first; ran it on 2026-10-29: `False error: unexpected argument(s) for delete_event: id 1 4`. Test `test_bad_arguments_are_refused`. **PASS**

**Q3. In `delete_by_title` the model deletes both `evt_002` and `evt_004`, then submits. Reward and problems?**
Answer: Reward 0.0. The one problem is `unexpected deletion: evt_004 ('Old sync' on cal_team 2026-11-09 14:00-15:00)`; `evt_002` was correctly removed so it is not listed.
Verified: `expect()` in `calendar_env.py` lists every id in `gone` that is not in `want_removed`; ran it on 2026-10-29 and got exactly that problem. **PASS**

**Q4. Does the model ever see its reward?**
Answer: No. The final observation content is only `episode over (<reason>)`; reward and problems are in `Observation.metadata` and `State`, which the runner reads but does not put in a message (D8).
Verified: `Environment.finish` builds `content=f"episode over ({reason})"`; `run_episode` appends only `obs.content` to messages. Test `test_submit_ends_episode_and_step_after_done_raises` asserts `"reward" not in obs.content`. **PASS**

**Q5. With `max_steps=2`, what does the second `list_calendars` call return?**
Answer: The calendar list followed by a new line and `episode over (step_limit)`, with `done=True`, `ok=True`, and the reward of the state check (0.0 for `create_explicit`, since nothing was created).
Verified: `Environment.step` appends `end.content` to the tool result when `step_count >= max_steps`; ran it on 2026-10-29: content ends with `episode over (step_limit)`, `done True`, reward `0.0`. Test `test_step_limit_ends_episode_on_last_step`. **PASS**

Day 1 result: 5/5 PASS.

## Day 2 (2026-10-30)

**Q6. In `create_by_name` the model first calls `list_events` with `calendar_id` "Personal" (refused), then `list_calendars`, then the right `create_event`, then submits. Passed, reward, and what does the breakdown say?**
Answer: Passed, reward 0.96. The refused call costs 0.2 of the trajectory score (0.8); accepted work steps are 2, equal to the reference, so no extra step charge. 0.8 x 1.0 + 0.2 x 0.8 = 0.96. The tree is gate 0.960 > state 1.000 and outcome_and_process 0.960 > state x0.8 1.000, trajectory x0.2 0.800 with "1 refused step(s) -0.2".
Verified: ran exactly this episode on 2026-10-30 and printed `breakdown_lines`: `0.96 True`, tree as stated. **PASS**

**Q7. In `delete_by_title` the model lists calendars twice, lists events, deletes `evt_002` and `evt_004`, then submits. Reward?**
Answer: 0.0. The state check finds `unexpected deletion: evt_004`, so the gate stops at "state scored 0 < 1, inner rubric not scored" and the extra lookup is never charged. passed is False.
Verified: ran it on 2026-10-30: `0.0 False`, breakdown has only the gate and the state child with that problem. `Gate.score` returns before scoring `inner`. **PASS**

**Q8. Does the `submit` call count as a step over the reference in `TrajectoryRubric`?**
Answer: No. `RubricContext.work_steps` drops `submit` before counting, and `Task.reference` never includes submit, so a clean reference run with submit scores 1.0.
Verified: `work_steps` filters `s.tool != SUBMIT`; test `test_trajectory_clean_run_is_one_and_submit_not_counted`. **PASS**

**Q9. A refused `create_event` (overlap) is followed by a correct one in `first_free_slot`. Is the refused one also counted as an extra step?**
Answer: No. Extra steps count only accepted work steps beyond `len(reference)`: 3 accepted (list_calendars, list_events, create_event) vs a reference of 3, so 0 extra and 1 refused: reward 0.96.
Verified: `TrajectoryRubric.score` uses `accepted = len(work) - refused`; test `test_env_records_steps_and_breakdown_messy_but_correct` asserts 0.96 and passed. **PASS**

Day 2 result: 4/4 PASS.

## Day 3 (2026-10-31)

**Q10. In `delete_by_title` the model skips `list_calendars`, calls `list_events` with `cal_team` and `2026-11-02`, deletes `evt_002` and submits. Passed, reward, failures?**
Answer: Passed, reward 1.0 (2 accepted work steps, fewer than the reference of 3, nothing refused). One failure: step 1 `list_events` is `wrong_order` ("called before list_calendars"); the delete is not flagged again because each missing prerequisite is reported once. The failure does not lower the reward (D19).
Verified: ran it on 2026-10-31: `True 1.0 [{'index': 1, 'tool': 'list_events', 'kind': 'wrong_order', 'reason': 'called before list_calendars'}]`. Test `test_wrong_order_reports_each_missing_prerequisite_once`. **PASS**

**Q11. In `create_by_name` the first call is `list_events` with `calendar_id` "Personal". Which failure kind, and why not `wrong_arguments`?**
Answer: `invented_id`. The arguments fit the schema (a string), so `validate_args` accepts them; the handler then raises `UnknownIdError` because no calendar has that id, the env tags the step `unknown_id`, and that maps to `invented_id`. After the lookup and correct create the run passes with reward 0.96.
Verified: `CalendarEnv._calendar` raises `UnknownIdError`; `Environment._call` catches it before `ToolError`; ran it on 2026-10-31: `True 0.96`, kind `invented_id`, reason `refused (unknown_id)`. **PASS**

**Q12. In `delete_by_title` the model calls `list_calendars` twice and then plays the reference. Failure kind and reward?**
Answer: Step 2 is `repeated_lookup` (identical read only call). Reward 0.98: 4 accepted work steps vs a reference of 3 is one extra step, trajectory 0.9, 0.8 + 0.2 x 0.9.
Verified: ran it on 2026-10-31: `True 0.98`, one failure at index 2 `repeated_lookup`. `classify` checks the repeat before the reference count, so it is not labelled `extra_step`. **PASS**

**Q13. In `first_free_slot` the model books with start "3pm", is refused, then books 15:00 to 16:00 correctly. What kind is the refused step?**
Answer: `wrong_arguments`. The schema accepts any string, the handler raises a plain `ToolError` ("start must be HH:MM"), the env tags it `tool_error`, and `REFUSED_KIND` maps `tool_error` to `wrong_arguments`. Reward 0.96.
Verified: ran it on 2026-10-31: `True 0.96`, failure index 3 `create_event` `wrong_arguments`, reason `refused (tool_error)`. **PASS**

Day 3 result: 4/4 PASS.

## Day 4 (2026-11-01)

**Q14. In `close_by_name` the model searches "login loop", then closes T-1003 instead of T-1002, and submits. Passed, reward, problems, failure kinds?**
Answer: Not passed, reward 0.0 (gate). Two problems: T-1002 status is still open, and an unexpected change to T-1003 status. No failure kinds: the tools and their order match the reference, and `classify` does not compare arguments (D18), so the wrong target shows only as problems (D24).
Verified: ran it on 2026-11-01: `False 0.0 ["T-1002 status is 'open', expected 'closed'", "unexpected change to T-1003 status: 'open' -> 'closed'"] []`. Test `test_close_wrong_same_subject_ticket_fails`. **PASS**

**Q15. In `assign_by_name` the model skips both lookups and calls `assign_ticket(T-1001, agt_01)` straight away, then submits. Passed, reward, failures?**
Answer: Passed, reward 1.0 (one accepted work step, below the reference of 3, nothing refused). One failure: `wrong_order` on step 1, reason "called before list_agents, search_tickets" (both missing prerequisites in one failure, each reported once). The guessed ids happen to be right; the failure makes the guess visible without lowering the reward (D19).
Verified: ran it on 2026-11-01: `True 1.0 [{'index': 1, 'tool': 'assign_ticket', 'kind': 'wrong_order', 'reason': 'called before list_agents, search_tickets'}]`. Test `test_name_variant_with_guessed_ids_passes_but_shows_wrong_order`. **PASS**

**Q16. What does the messy control produce on `close_by_name`, and what is its reward?**
Answer: The noise lookup on the inbox env is `list_agents` (first argument free read only tool). `close_by_name`'s reference never uses it, so the kinds are `wrong_tool` (guess_id) then `extra_step`. Accepted work steps: list_agents, search_tickets, set_status = 3 vs a reference of 2, so 1 extra and 1 refused: trajectory 1 - 0.2 - 0.1 = 0.7, reward 0.8 + 0.2 x 0.7 = 0.94.
Verified: ran it on 2026-11-01: `True 0.94 ['wrong_tool', 'extra_step']`. Test `test_messy_expected_per_env`. **PASS**

**Q17. `python3 quiz/quiz_model.py --fake --only delete_by_title`: what does the gap table say, and why?**
Answer: One row, `calendar/cancel_old_sync` with id 0/0 and name 1/1, marked "one variant only, not in total", and the last line ends with "gap n/a". `id_name_gap` adds a pair to the totals only when both variants ran (D21), so a filtered run cannot show a fake gap. The run still exits 0 because a fake gap of n/a is allowed (D23).
Verified: test `test_only_filter_and_no_match` asserts "1/1 tasks passed", "one variant only, not in total" and "gap n/a" with exit 0. **PASS**

Day 4 result: 4/4 PASS.

## Day 5 (2026-11-02)

**Q18. `create_by_name` is run with the reference on seed 2 and recorded; the record's seed is changed to 9 and replayed. Result, and which mismatch comes first?**
Answer: Not ok, but reward still 1.0 (the outcome is the same). First mismatch is step 1 `list_calendars`, because the seed shuffles the calendar list; the second is step 2 `create_event`, because the seed also moves the new event id.
Verified: ran it on 2026-11-02: `False 1.0`, mismatches start `step 1 list_calendars: observation differs` then `step 2 create_event: observation differs (recorded 'created evt_854', replayed 'created evt_988')`. Test `test_wrong_seed_first_mismatch_is_the_lookup`. **PASS**

**Q19. `create_by_name` with `max_steps=3` and a model that calls `list_calendars` 5 times ends on `step_limit`. The last step is removed from the record and it is replayed. What does replay report?**
Answer (first): one mismatch, "recorded end 'step_limit' but the replayed episode is still running"; replay then calls `finish(step_limit)`, reward 0.0 both times.
Verified: ran it on 2026-11-02: two mismatches, the one above plus `failures: recorded ['repeated_lookup', 'repeated_lookup'], replayed ['repeated_lookup']`. The removed step was itself a repeated lookup, so the replayed failure kinds differ too. **FAIL**, fixed in the answer (D29): two mismatches, end and failures; reward 0.0. Test `test_truncated_step_limit_record_shows_end_and_failure_diff`. Re-verified: **PASS**

**Q20. The model answers "All set" without a tool call on `close_by_name`. What is recorded, and how does replay reach the same end?**
Answer: End `no_submit`, reward 0.0, zero steps. Replay steps nothing, sees the env still running and, since `no_submit` is not an end the env produces itself, calls `finish("no_submit")` (D27). Same reward, ok.
Verified: ran it on 2026-11-02: `no_submit 0.0 0 True 0.0`. Test `test_replay_reproduces_every_end_reason`. **PASS**

**Q21. On seeds 1, 2 and 3 the inbox tickets come back in a different order. Why does the `close_by_name` reference still pass clean?**
Answer: `seeded` only reorders lists (D25). The reference closes `T-1002` by id, `expect_changes` compares tickets by id, and `classify` compares tools and order, not list positions, so neither the check nor the failure kinds depend on order.
Verified: ran it on 2026-11-02: ticket orders `T-1004, T-1005, T-1002, ...` (seed 1), `T-1004, T-1002, ...` (seed 2), `T-1002, T-1001, ...` (seed 3); quiz_model `--fake` runs every reference on seeds 1 to 3: "72/72 controls behaved as expected". Test `test_every_reference_passes_clean_on_many_seeds` (25 seeds). **PASS**

Day 5 result: 3/4 PASS on first answer, 1 FAIL fixed (Q19), 4/4 PASS after the fix.

## Day 6 (2026-11-03)

**Q22. In `delete_by_title` the model looks up the calendar, lists Team events without a date, deletes `evt_004`, then deletes `evt_002` and submits. Passed, reward, failure kinds?**
Answer: Not passed, reward 0.0 (gate): one problem, the unexpected deletion of `evt_004`. One failure only: step 3 `delete_event` is `wrong_target` (event_id evt_004, reference evt_002). Step 4 is not an `extra_step`, because a wrong target call does not use up the reference's one `delete_event` (D30), and the dateless `list_events` is fine because `date` is not an id argument.
Verified: ran it on 2026-11-03: `False 0.0 [(3, 'wrong_target')] ["unexpected deletion: evt_004 ('Old sync' on cal_team 2026-11-09 14:00-15:00)"]`. Test `test_wrong_target_does_not_use_up_the_reference_call`. **PASS**

**Q23. In `first_free_slot` the model books the Retro at 14:00 on `cal_team` and submits. Is that a `wrong_target`?**
Answer: No. 14:00 overlaps "Old sync", so the env refuses the create with a `ToolError` and the kind is `wrong_arguments` (refused, tool_error). Even if the env had accepted a wrong time, `calendar_id` matches the reference and times are not id arguments, so it would never be `wrong_target`; the missing event shows as a problem, reward 0.0.
Verified: ran it on 2026-11-03: `False 0.0`, failure index 3 `create_event` `wrong_arguments` reason `refused (tool_error)`, problem `missing event: 'Retro' on cal_team 2026-11-02 15:00-16:00`. Test `test_non_id_arguments_never_make_a_wrong_target`. **PASS**

**Q24. `python3 -m agent_gym eval --env inbox --repeats 2`: which seeds, how many episodes, and what happens when Ollama is not running?**
Answer: Seeds 1 and 2 (`eval_seeds(2, None)` counts up from 1), 6 inbox tasks x 2 = 12 episodes. With Ollama down the check runs before any episode: it prints `PROBLEM: ...` and exits 4.
Verified: test `test_cli_eval_pass_json_and_record` (12 runs, seeds `[1, 2]`) and `test_cli_eval_usage_and_ollama` (exit 4); ran `eval --env inbox --model nonexist:1b` on the Mac on 2026-11-03 with Ollama off: `PROBLEM: Ollama is not reachable ...`. **PASS**

**Q25. `report` on a JSONL file that holds only a blank line, on a missing file, and on a record without `task_id`: exit codes?**
Answer: 3 (no records: nothing to report), 2 (cannot read), 2 (bad record field). Exit 1 is kept for runs that actually failed (D33).
Verified: test `test_cli_report_exit_codes` covers all three; `report /nonexistent` exited 2 on 2026-11-03. **PASS**

Day 6 result: 4/4 PASS.
