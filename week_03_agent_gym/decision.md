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
