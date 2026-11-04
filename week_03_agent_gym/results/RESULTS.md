# Agent Gym results

Generated with `report --markdown` from the JSONL files in this folder. Every number can be rebuilt from the file without a model (`python3 -m agent_gym report FILE --markdown`) and every episode can be replayed (`python3 -m agent_gym replay FILE`).

## Scripted reference (pipeline check, not a model)

`fake_reference.jsonl`, written by `python3 quiz/quiz_model.py --fake --record results/fake_reference.jsonl`. A scripted client plays each task's reference solution, so this table shows the gym and the report working end to end: 100%, no failure kinds, gap 0. It says nothing about any real model.

Model: fake. Runs: 12, passed 12 (100%), mean reward 1.000. Seeds: canonical.

| task | passed | mean reward | wrong tool | wrong arguments | wrong target | wrong order | invented id | repeated lookup | extra step |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| calendar/create_explicit | 1/1 | 1.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| calendar/create_by_name | 1/1 | 1.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| calendar/create_by_id | 1/1 | 1.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| calendar/delete_by_title | 1/1 | 1.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| calendar/delete_by_id | 1/1 | 1.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| calendar/first_free_slot | 1/1 | 1.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| inbox/assign_by_id | 1/1 | 1.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| inbox/assign_by_name | 1/1 | 1.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| inbox/close_by_id | 1/1 | 1.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| inbox/close_by_name | 1/1 | 1.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| inbox/escalate_by_id | 1/1 | 1.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| inbox/escalate_by_name | 1/1 | 1.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **total** | **12/12** | **1.000** | **0** | **0** | **0** | **0** | **0** | **0** | **0** |

Failed runs with no failure kind: 0.

| pair | id variant | name variant |
| --- | ---: | ---: |
| calendar/dentist | 1/1 | 1/1 |
| calendar/cancel_old_sync | 1/1 | 1/1 |
| inbox/assign | 1/1 | 1/1 |
| inbox/close | 1/1 | 1/1 |
| inbox/escalate | 1/1 | 1/1 |

Pass rate with ids 100%, with names 100%, gap +0 points.

## qwen3:4b (to run on the Mac)

Not recorded yet. The daily automation runs in a shell that cannot reach Ollama on the Mac, so the real model table has to be produced locally (D35). With Ollama running:

```bash
cd week_03_agent_gym
export PYTHONPATH=src
ollama pull qwen3:4b
python3 -m agent_gym eval --repeats 3 --record results/qwen3_4b.jsonl     # 12 tasks x seeds 1, 2, 3
python3 -m agent_gym report results/qwen3_4b.jsonl --markdown >> results/RESULTS.md
```

What to read in that table: the total pass rate, which failure kind columns are not zero (Turing's Calendar Gym found right tool with wrong arguments to be the largest bucket), the id vs name gap (Turing: 89% vs 41%), and "Failed runs with no failure kind", which counts runs that failed without a wrong step (for example a run that only answered in text).
