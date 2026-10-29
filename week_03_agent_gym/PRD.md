# PRD: Agent Gym

**Week:** 03 (2026-10-29 to 2026-11-04)
**Stack:** Python 3.10+, Ollama (local, free), standard library only

## 1. Why this project

The research pass on 2026-10-29 found two threads that meet in one project:

* On 2026-10-22 the Agentic AI Foundation took on **OpenEnv** (from Hugging Face) next to Agent Skills, Open Responses and OpenSandbox. OpenEnv standardises agent environments behind a Gym style API: `reset()`, `step(action)` and a `state` property, with `done` and `reward` carried on the observation and rewards computed **inside** the environment by composable rubrics.
* The "fewer agents, stronger evidence" theme of the same week: agreement between models is weak evidence; a deterministic check of the outcome (a database state, a rule, a proof) is strong evidence. Cisco's Agentic FAITH (2026-10-24) scores intermediate decisions as well as outcomes, and Turing's Calendar Gym on OpenEnv found that most tool call failures are **right tool, wrong arguments** (51%), then wrong tool (23%) and wrong order (18%), and that agents do far worse with names than with explicit ids (41% vs 89%).

This project builds a small, readable, OpenEnv shaped gym in pure Python, runs a local model through it, and scores episodes by checking the final state, not the model's words. Week 01 controlled what tools an agent may call, week 02 what instructions enter its context; week 03 measures whether it actually did the job.

Sources: [AAIF announcement](https://www.linuxfoundation.org/press/agentic-ai-foundation-announces-four-new-projects-agent-skills-open-responses-openenv-and-opensandbox), [OpenEnv concepts](https://huggingface.co/docs/openenv/main/guides/concepts.md), [Turing: evaluating tool using agents with OpenEnv](https://www.turing.com/blog/evaluating-tool-using-agents-in-production-oriented-environments-with-openenv), [AI News vol. 54: fewer agents, stronger evidence](https://rickhigh.substack.com/p/ai-news-volume-54-fewer-agents-stronger), [AI agent news, week of 2026-10-29](https://aiagentstore.ai/ai-agent-news/this-week).

## 2. Goals

1. An `Environment` base class with the OpenEnv shape (`reset`, `step`, `state`), typed `Action` / `Observation` / `State`, argument validation and a step limit.
2. A calendar environment with tasks that need lookups (names, not ids) and a state based verifier that also catches collateral damage.
3. Composable rubrics (weighted sum, gate, trajectory penalties) so reward reflects outcome and process.
4. A failure taxonomy for every refused or wasted step: wrong tool, wrong arguments, wrong order, invented id.
5. Recorded trajectories (JSONL) that replay deterministically, and a CLI and quiz that report results per task and per failure kind.

## 3. Non goals

* No HTTP or Docker server: environments run in process (the client/server split of OpenEnv is out of scope).
* No training or RL. Rewards are for evaluation.
* No cloud or paid LLM APIs.

## 4. Users

A developer who wants to know whether a local model can really use a set of tools, and which kind of mistake it makes when it cannot.

## 5. Daily milestones

* [x] **Day 1 (Thu 10/29):** Research, PRD, decision log, flow, quiz. Core types, `Environment` base (reset, step, state, finish, argument validation, step limit, episode isolation), calendar environment with 4 tools and 4 tasks (explicit id, name lookup, ambiguous title, free slot), `expect()` state checks with collateral damage detection, `run_episode` agent loop, LLM clients copied from week 02, day 1 CLI (`list`, `run`), quiz_model with reference runs and zero score controls, tests.
* [ ] **Day 2 (Fri 10/30):** Rubrics: `Rubric` protocol with `StateCheck`, `WeightedSum`, `Gate` and a `TrajectoryRubric` that penalises refused steps and extra steps over the reference; reward breakdown in `Episode`.
* [ ] **Day 3 (Sat 10/31):** Failure taxonomy: classify each refused or wasted step (wrong tool, wrong arguments, wrong order, invented id, repeated lookup) against the task reference; counts per episode and per task.
* [ ] **Day 4 (Sun 11/01):** Second environment (ticket inbox) and paired task variants (explicit id vs name) to measure the id vs name gap on the local model.
* [ ] **Day 5 (Mon 11/02):** Trajectories: JSONL recording of every episode and `replay` that re-runs the actions against a fresh env and must reproduce the reward; seeded task data.
* [ ] **Day 6 (Tue 11/03):** CLI: `list`, `run`, `eval` (all tasks, N repeats), `replay`, `report` with `--json` and fixed exit codes.
* [ ] **Day 7 (Wed 11/04):** Close out: real model results table (pass rate, failure kinds, id vs name gap), README demo, retro in decision.md, project closed in state.json.

## 6. Success criteria

* `python3 -m pytest -q` passes with the fake LLM, no Ollama needed.
* `python3 quiz/quiz_model.py --fake` passes, and the "do nothing" controls score 0 on every task.
* Reward never depends on what the model says, only on the final environment state (and, from day 2, its recorded steps).
* On `qwen3:4b` every failure in the results table has a failure kind.
