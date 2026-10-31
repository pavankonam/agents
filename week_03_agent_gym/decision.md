# Decision Log: Agent Gym

Each entry: what was decided, why, and what else was considered. New entries are appended at the bottom.

## D1. Project topic: OpenEnv shaped environments with outcome checks (2026-10-29)

**Decision:** Build a small gym of agent environments with the OpenEnv API shape and score local model runs by the final state.
**Why:** OpenEnv joined the Agentic AI Foundation on 2026-10-22, and the same week's commentary ("fewer agents, stronger evidence") argued for deterministic outcome checks over model agreement. It is also the natural next step in the series: week 01 limited tools, week 02 managed instructions, week 03 measures whether the work was done.
**Alternatives:** An agent memory layer with belief revision (interesting, but hard to evaluate without exactly this kind of harness first), a sandbox for agent code (Akamai and Daytona news; needs containers), a multi agent governance demo (SK Telecom style IDs and supervisors; less to measure).

## D2. First environment: a calendar (2026-10-29)

**Decision:** Start with an in-memory calendar: calendars, events, four tools (`list_calendars`, `list_events`, `create_event`, `delete_event`).
**Why:** Turing's Calendar Gym is the best documented OpenEnv evaluation and its findings (argument errors dominate, names are much harder than ids) are things a local model can reproduce. A calendar is small enough to read in one file and its state is easy to compare.
**Alternatives:** A file system env (overlaps week 01), a shop or inventory env (more rules to explain).

## D3. In process environments, no server (2026-10-29)

**Decision:** Environments are plain Python objects; `reset`/`step`/`state` are method calls.
**Why:** OpenEnv runs environments as FastAPI servers in Docker, which is right for training at scale but adds setup that hides the idea. The API shape is kept, so a server wrapper could be added later without changing environments.
**Alternatives:** Depend on the `openenv` package (pulls in FastAPI, Pydantic and Docker tooling; breaks "stdlib only").

## D4. Stdlib dataclasses for Action, Observation, State (2026-10-29)

**Decision:** `Action(tool, arguments)`, `Observation(content, ok, done, reward, metadata)`, `State(episode_id, task_id, step_count, done, reward, end_reason, problems)`.
**Why:** Same field names as OpenEnv where they exist (`done` and `reward` on the observation, `episode_id` and `step_count` on the state) with zero dependencies. `ok` is added so a refused action is visible without parsing text.
**Alternatives:** Pydantic models (validation for free, but a dependency), tuples like classic Gym (`obs, reward, done, info`), which OpenEnv moved away from.

## D5. LLM runtime: Ollama over plain HTTP, default `qwen3:4b`, override with `AGENT_GYM_MODEL` (2026-10-29)

**Decision:** Same client as weeks 01 and 02.
**Why:** Free, local, native tool calling, no SDK. A 4B model is the honest test for a tool use benchmark.

## D6. Copy `llm.py` from week 02 instead of importing it (2026-10-29)

**Decision:** Copied with the env var renamed.
**Why:** One folder, one project, as in weeks 01 and 02.

## D7. Reward comes only from the environment's final state (2026-10-29)

**Decision:** When an episode ends, the task's `check(initial, final)` returns a list of problems; reward is 1.0 if the list is empty, else 0.0. The model's summary is recorded but never scored.
**Why:** This is the "stronger evidence" point: a deterministic check of the outcome beats asking a model whether it succeeded. Day 2 adds process terms through rubrics, still computed inside the env.
**Alternatives:** LLM as judge on the final answer (weak evidence, needs a second model), string matching on the answer (rewards claims, not actions).

## D8. The agent never sees its reward or the check's problems (2026-10-29)

**Decision:** The final observation says only `episode over (<reason>)`; reward and problems go in `metadata` and `State`, which the runner reads but does not send to the model.
**Why:** Keeps evaluation separate from the episode, and stops a later multi try loop from simply reading the answer key.

## D9. Checks compare full state and flag collateral damage, with a trap event (2026-10-29)

**Decision:** `expect(added=..., removed=...)` requires exactly those changes: any extra event, extra deletion, changed event or changed calendar is a problem. The seed data holds two "Old sync" events a week apart, so "cancel the Old sync on 11/02" fails if the model deletes the wrong one or both.
**Why:** Turing found agents guess ids and act on the wrong record; an outcome check that only looks for the target would miss that. Titles match ignoring case and outer spaces, times and dates must match exactly.

## D10. Episode end reasons: submitted, step_limit, no_submit, turn_limit (2026-10-29)

**Decision:** `submit` is a tool and ends the episode. If the model replies with text and no tool call, the runner ends the episode as `no_submit` and the state is still scored. The env ends at `max_steps` tool calls (`step_limit`); the runner also stops after `max_turns` model calls (`turn_limit`).
**Why:** Small models often stop with a sentence instead of calling submit. Scoring the state anyway measures the work, and the end reason keeps the protocol slip visible (day 2 rubrics can penalise it).
**Alternatives:** Nudge the model to call submit (adds turns and hides the slip), score `no_submit` as 0 (punishes protocol, not work).

## D11. Refused actions count as steps and are returned to the model (2026-10-29)

**Decision:** Unknown tools, argument problems (missing, unexpected, wrong type, including `_raw` from unparseable JSON) and tool errors return `ok=False` with an `error:` message; the step still counts toward the limit.
**Why:** Lets the model recover, as a real API would, while the cost of mistakes shows up in step counts. These refused steps are what the day 3 failure taxonomy classifies.

## D12. quiz_model runs zero score controls in fake mode (2026-10-29)

**Decision:** Besides the scripted reference run per task, `--fake` runs two controls per task (answer without acting, submit at once) that must score 0.
**Why:** A verifier that passes when nothing happened is worthless; the controls prove each check is not trivially satisfied.

## D13. Rubrics are small composable objects that return a score tree (2026-10-30)

**Decision:** A `Rubric` has a `name` and `score(ctx) -> RubricResult(name, score, detail, children, weight)`. Four are built in: `StateCheck`, `TrajectoryRubric`, `WeightedSum`, `Gate`. The env builds a `RubricContext` (initial data, final data, a `StepLog` per step, the task reference, end reason) in `finish()` and stores the result tree as `State.breakdown`.
**Why:** OpenEnv computes rewards inside the environment with composable rubrics; a tree that keeps every child score and a one line reason per penalty makes a low reward explainable without rerunning the episode. Plain classes with a protocol keep it stdlib only.
**Alternatives:** One hard coded reward formula in `finish()` (no way to vary it per task), a flat dict of named terms (loses how terms combine), an LLM judge for process quality (weak evidence, D7).

## D14. Default reward: Gate(state) over 0.8 state + 0.2 trajectory; tasks may override (2026-10-30)

**Decision:** `default_rubric(check)` gates on the state check and then takes 0.8 of the outcome plus 0.2 of the trajectory score. `TrajectoryRubric` charges 0.2 per refused step and 0.1 per accepted work step beyond `len(reference)`; a refused step is not also counted as extra, `submit` is never counted, and the score is clipped at 0. `Task.rubric` replaces the default when set.
**Why:** The outcome must dominate: a run that leaves the wrong state is worth 0 however tidy it was, and a correct run never drops below 0.8. Refusals cost more than extra steps because a refused call is a real tool use error (Turing: wrong arguments 51%, wrong tool 23%), while an extra lookup is only waste. The penalties are round numbers that are easy to check by hand in the quiz.
**Alternatives:** Pure weighted sum without a gate (a failed run with a clean trajectory would earn 0.2), multiplying outcome by process (same ordering, harder to read), counting the submit step (penalises the one call we ask for).

## D15. `passed` is separate from `reward`, and `Episode.success` means passed (2026-10-30)

**Decision:** `State.passed` and `Episode.passed` are True when the state check returns no problems. `Episode.success` now returns `passed` instead of `reward == 1.0`. `problems` stay the state check problems. The CLI exit code and the quiz PASS still follow success.
**Why:** With process terms a correct but messy run scores e.g. 0.96; calling that a failure would merge two questions (did it do the job, how well) that the day 7 results table must keep apart: pass rate and mean reward.
**Alternatives:** Keep success as reward 1.0 (any refused step would count as a failed task), a reward threshold like 0.9 (arbitrary and depends on the rubric).

## D16. quiz_model adds a "messy but correct" control (2026-10-30)

**Decision:** In `--fake` mode each task also runs a script that calls an unknown tool once, repeats `list_calendars`, then plays the reference solution. It must pass and score strictly between 0 and 1.
**Why:** The zero score controls (D12) prove the outcome check is not trivially satisfied; this one proves the process rubric is actually wired in. If someone removed the trajectory term, every task would score 1.0 and the control would fail.


## D17. The env tags every refused step with an error kind; unknown ids get their own exception (2026-10-31)

**Decision:** `Environment._call` puts `error_kind` in the refused observation's metadata and the env copies it into `StepLog.error_kind`: `unknown_tool`, `bad_arguments` (from `validate_args`), `unknown_id` (the new `UnknownIdError`, a subclass of `ToolError`) or `tool_error` (any other `ToolError`). The calendar env raises `UnknownIdError` for an unknown calendar or event id.
**Why:** The env already knows why it refused a step; recovering that later by parsing error text would break as soon as a message is reworded. A subclass keeps old `except ToolError` code working and lets each env decide what counts as an id.
**Alternatives:** Regex over the `error:` text (fragile), an `ids` registry per env that the classifier checks (more code per env for the same answer).

## D18. Failure taxonomy: six kinds, one per wasted step, judged against the task reference (2026-10-31)

**Decision:** `failures.classify(steps, reference, specs)` gives each refused or wasted work step one kind: `wrong_tool`, `wrong_arguments`, `wrong_order`, `invented_id`, `repeated_lookup`, `extra_step`. Refused steps map from the error kind (a tool error such as an overlap or a bad date is `wrong_arguments`, the values were wrong). Accepted steps are checked in this order: identical read only repeat, tool outside the reference (write = `wrong_tool`, lookup = `extra_step`), more calls of a tool than the reference makes (`extra_step`), and a reference prerequisite not yet accepted (`wrong_order`, each missing prerequisite reported once so one skipped lookup is one failure). `ToolSpec.read_only` marks lookups. Results are stored as `State.failures` and `Episode.failures`; `count_kinds` and `summarize` count them per episode and per task.
**Why:** The PRD's day 7 table must say which mistake a local model makes, not only how often it fails. The first four kinds are Turing's categories; `repeated_lookup` and `extra_step` cover the waste that `TrajectoryRubric` already charges. One kind per step keeps counts additive. Flagging a guessed id that happened to be right (writing in `create_by_name` before `list_calendars`) as `wrong_order` makes the id vs name gap visible on day 4 even when the outcome passes.
**Alternatives:** Several kinds per step (counts no longer add up to wasted steps), an LLM labelling the trajectory (weak evidence, D7), comparing arguments with the reference too (most tasks have more than one valid argument set, e.g. the `date` filter on `list_events` is optional).

## D19. The taxonomy explains the reward and never changes it (2026-10-31)

**Decision:** `classify` runs in `Environment.finish` after the rubric; nothing in the rubric reads it. A run can have reward 1.0 and still list a `wrong_order` failure (skipped lookup, right guess).
**Why:** Reward is the score, failures are the diagnosis. Feeding the taxonomy into the reward would charge the same refused step twice and tie the reward to classification rules that may still change this week.

## D20. quiz_model checks the taxonomy and prints a failure table (2026-10-31)

**Decision:** In `--fake` mode a reference run counts as passed only if it has no failures, and the messy control must produce exactly `wrong_tool` then `repeated_lookup` (or `extra_step` on `create_explicit`, whose reference has no lookup). Every run, fake or real, ends with a table of failure kinds per task with a total row.
**Why:** Same idea as the controls in D12 and D16: prove the classifier fires on known mistakes and stays silent on a clean run. The table is the shape of the day 7 results.
