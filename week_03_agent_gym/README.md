# Week 03: Agent Gym

A small **OpenEnv shaped gym** for tool using agents on a **free local model through Ollama**. Environments expose `reset()`, `step(action)` and `state`; a local model drives them through tool calls; and every episode is scored by checking the environment's **final state**, never by trusting what the model says it did. See [PRD.md](PRD.md) for the plan, [flow.md](flow.md) for how it works and [decision.md](decision.md) for why.

**Status:** Day 2 of 7. Core types, `Environment` base with argument validation and step limit, a calendar environment with four tools and four tasks (explicit id, name lookup, ambiguous title with a trap event, first free slot), state checks that also catch collateral damage, the episode runner, a small CLI and a model quiz with zero score controls. New on day 2: composable **rubrics** (`StateCheck`, `TrajectoryRubric`, `WeightedSum`, `Gate`). The default reward gates on the final state, then gives 0.8 for the outcome and 0.2 for a clean trajectory (minus 0.2 per refused step, 0.1 per step over the reference). `passed` (state check clean) is kept separate from `reward`, and every episode carries its rubric tree as `breakdown`. 88 tests.

## Run it

```bash
ollama pull qwen3:4b          # once
cd week_03_agent_gym
export PYTHONPATH=src

python3 -m agent_gym list                          # environments and tasks
python3 -m agent_gym run create_by_name            # one episode with qwen3:4b
python3 -m agent_gym run delete_by_title --json    # full episode record
python3 -m agent_gym run first_free_slot --breakdown   # rubric tree: why the reward is what it is
AGENT_GYM_MODEL=llama3.2 python3 -m agent_gym run first_free_slot --max-steps 8
```

Each run prints every step (`ok` or `ERR`, the tool, its arguments, the result), then PASS or FAIL (state check), the reward (rubric score), the end reason (`submitted`, `no_submit`, `step_limit`, `turn_limit`) and, on failure, the problems the state check found. Exit code 0 means the state check passed (reward may be below 1.0 for a messy run), 1 means the task failed, 2 is a usage error and 4 means Ollama is not ready.

## Quiz the model

```bash
python3 quiz/quiz_model.py --fake          # scripted reference solutions, no Ollama
python3 quiz/quiz_model.py                 # qwen3:4b on every task
python3 quiz/quiz_model.py --only delete --model llama3.2
```

In `--fake` mode each task also runs two controls (answer without acting, submit at once) that must score 0, which proves the checks are not trivially satisfied, and a "messy but correct" control (one unknown tool call and a repeated lookup before the reference) that must pass with a reward strictly between 0 and 1, which proves the process rubric is live.

Example breakdown for a correct run with one refused call:

```
gate: 0.960
  state: 1.000
  outcome_and_process: 0.960
    state x0.8: 1.000
    trajectory x0.2: 0.800
      - 1 refused step(s) -0.2
```

## Tests

```bash
pip install pytest
python3 -m pytest -q
```

The tests use a scripted fake model, so no Ollama is needed.

## Layout

| Path | What |
| --- | --- |
| `src/agent_gym/types.py` | `Action`, `Observation`, `State` |
| `src/agent_gym/env.py` | `Environment` base, `ToolSpec`, `Param`, `Task`, `validate_args` |
| `src/agent_gym/envs/calendar_env.py` | Calendar environment, its tasks and the `expect()` state check |
| `src/agent_gym/rubrics.py` | `StateCheck`, `TrajectoryRubric`, `WeightedSum`, `Gate`, `default_rubric` |
| `src/agent_gym/agent.py` | `run_episode` and `Episode` |
| `src/agent_gym/llm.py` | Ollama and fake clients (copied from week 02) |
| `src/agent_gym/cli.py` | `list` and `run` (with `--breakdown`) |
| `quiz/` | Self quiz and the model quiz |
