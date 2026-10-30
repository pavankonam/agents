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
