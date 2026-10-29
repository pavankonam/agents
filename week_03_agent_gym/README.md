# Week 03: Agent Gym

A small **OpenEnv shaped gym** for tool using agents on a **free local model through Ollama**. Environments expose `reset()`, `step(action)` and `state`; a local model drives them through tool calls; and every episode is scored by checking the environment's **final state**, never by trusting what the model says it did. See [PRD.md](PRD.md) for the plan, [flow.md](flow.md) for how it works and [decision.md](decision.md) for why.

**Status:** Day 1 of 7. Core types, `Environment` base with argument validation and step limit, a calendar environment with four tools and four tasks (explicit id, name lookup, ambiguous title with a trap event, first free slot), state checks that also catch collateral damage, the episode runner, a small CLI and a model quiz with zero score controls. 70 tests.

## Run it

```bash
ollama pull qwen3:4b          # once
cd week_03_agent_gym
export PYTHONPATH=src

python3 -m agent_gym list                          # environments and tasks
python3 -m agent_gym run create_by_name            # one episode with qwen3:4b
python3 -m agent_gym run delete_by_title --json    # full episode record
AGENT_GYM_MODEL=llama3.2 python3 -m agent_gym run first_free_slot --max-steps 8
```

Each run prints every step (`ok` or `ERR`, the tool, its arguments, the result), then the reward, the end reason (`submitted`, `no_submit`, `step_limit`, `turn_limit`) and, on failure, the problems the state check found. Exit code 0 means reward 1.0, 1 means the task failed, 2 is a usage error and 4 means Ollama is not ready.

## Quiz the model

```bash
python3 quiz/quiz_model.py --fake          # scripted reference solutions, no Ollama
python3 quiz/quiz_model.py                 # qwen3:4b on every task
python3 quiz/quiz_model.py --only delete --model llama3.2
```

In `--fake` mode each task also runs two controls (answer without acting, submit at once) that must score 0, which proves the checks are not trivially satisfied.

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
| `src/agent_gym/agent.py` | `run_episode` and `Episode` |
| `src/agent_gym/llm.py` | Ollama and fake clients (copied from week 02) |
| `src/agent_gym/cli.py` | `list` and `run` |
| `quiz/` | Self quiz and the model quiz |
