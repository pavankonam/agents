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
