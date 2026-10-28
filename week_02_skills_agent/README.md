# Week 02: Skills Agent

A small agent that uses **Agent Skills** (folders with a `SKILL.md` file) on a **free local model through Ollama**. The model only sees each skill's name and description, and loads the full instructions when a task needs them (progressive disclosure). See [PRD.md](PRD.md) for the plan, [flow.md](flow.md) for how it works and [decision.md](decision.md) for why.

**Status:** Done (2026-10-22 to 2026-10-28). Skill parser and validator, discovery with rejected list, catalog in the system prompt (level 1), `load_skill` tool (level 2), `read_skill_file` for files bundled with a skill (level 3, confined to the skill folder), `run_skill_script` for scripts a skill permits in `allowed-tools` (no shell, timeout, output cap), a context budget that meters every run and refuses disclosures past a limit, a report comparing progressive disclosure with pasting every skill, a routing eval (description linter, near miss and two skill scenarios, per skill precision and recall), a CLI (`list`, `validate`, `inspect`, `run`, `doctor`), quiz reports saved as JSON and turned into a results table, five example skills, 184 tests. The retro is at the end of [decision.md](decision.md).

## Run it

```bash
ollama pull qwen3:4b          # once
cd week_02_skills_agent
export PYTHONPATH=src

python3 -m skills_agent doctor        # Python, skills and Ollama ready?
python3 -m skills_agent "What does BHX stand for?"
python3 -m skills_agent run "Convert 26.2 miles to km"
python3 -m skills_agent "Checkout is down for 40% of users. How severe is this?"
python3 -m skills_agent "What is the full ticket ID with check letter for HX-40217?"
SKILLS_AGENT_MODEL=llama3.2 python3 -m skills_agent "Write a commit message for: add retry to the HTTP client"
```

The first line of output shows which skills the model loaded, which skill files it read, which skill scripts it ran and roughly how many tokens the run put into the context. Add `--budget 1200` before the task to cap that (see below).

## CLI

```bash
python3 -m skills_agent list                     # valid skills, file and script counts, rejected ones
python3 -m skills_agent validate [--strict]      # exit 1 on a rejected skill (strict: also warnings, lint)
python3 -m skills_agent inspect ticket-checksum  # fields, files, runnable scripts, token cost; --body
python3 -m skills_agent run [--budget N] [--model M] [--max-steps N] "task"
python3 -m skills_agent doctor [--model M] [--offline]
python3 -m skills_agent list --skills-dir ~/my-skills --skills-dir skills --json
```

Every command takes `--json` and one or more `--skills-dir` (searched in order, the first skill with a name wins, duplicates are reported as rejected). A bare task still means `run`; a task that starts with a command word needs `run` in front (`run list my files`).

| Exit code | Meaning |
| --- | --- |
| 0 | ok (`list` and `inspect` are views and exit 0 even with rejected skills) |
| 1 | a check failed: `validate` found a rejected skill, or `doctor` found a failure other than Ollama |
| 2 | usage error, for example no task or `--budget 0` |
| 3 | `run` stopped at the step limit without a final answer |
| 4 | Ollama is not reachable or the model is not pulled (`run`, or `doctor` when that is the only failure) |
| 5 | `inspect` of a skill that does not exist |

`doctor` reports each check as OK, WARN or FAIL: Python 3.10+, skills roots exist, at least one valid skill, rejected skills (warn; the shipped `broken_skill` is one on purpose), description lint (warn), `/bin/sh` when a permitted `.sh` script exists, and Ollama up with the model pulled (`--offline` skips it).

## Three levels of disclosure

| Level | What the model sees | When |
| --- | --- | --- |
| 1 | Name and description of every skill | Always, in the system prompt |
| 2 | The `SKILL.md` body, plus the names of the other files in the folder | After `load_skill(name)` |
| 3 | One bundled file, for example `references/severity-matrix.md` | After `read_skill_file(skill, path)`, only for a loaded skill |

Level 3 reads are refused for absolute paths, `..`, hidden files, `SKILL.md` itself and symlinks that lead outside the skill folder. Files are capped at 16 KB of UTF-8 text; longer ones are truncated with a note.

## Skill scripts

A skill can ship helper programs in `scripts/` and let the model run them with `run_skill_script(skill, script, args)`. Nothing runs unless the skill grants it in its frontmatter:

```yaml
allowed-tools: run_skill_script(scripts/check_letter.py)   # one script
allowed-tools: run_skill_script                            # every script in scripts/
```

Rules: only `.py` (run with this Python in isolated mode) and `.sh` (run with `/bin/sh`) files inside `scripts/`, after the skill was loaded; no shell, so args are passed exactly as given; working directory is the skill folder; no stdin; a minimal environment (your shell's tokens and keys are not passed on); 10 second timeout that kills the script and its children; at most 8 KB of stdout and of stderr reach the model.

This is a guard rail, not a sandbox: a permitted script can still read and write files your user account can. Only grant `run_skill_script` to skills you have read.

## Context budget

Progressive disclosure exists to keep the context small. `budget.py` measures that, estimating tokens as characters / 4:

```bash
PYTHONPATH=src python3 -m skills_agent.budget          # table; add --json for machine output
```

With the shipped skills (estimated tokens):

| | Tokens |
| --- | --- |
| Progressive, before any load (prompt 586 + tool schemas 333) | 919 |
| Progressive, one average skill used | 1,155 |
| Progressive, every skill and file loaded | 2,100 |
| Paste every skill and file into the prompt | 1,316 |

So with five small skills progressive disclosure saves 30% before a load and 12% with one skill used, and it loses if a task needs every skill, because the rules and tool schemas are a fixed overhead. It pays off as the library grows: at 20 skills of the same size one used skill costs about 2,241 tokens against 4,859 pasted, at 100 skills 8,033 against 23,755.

Every run reports its cost in `AgentResult.context` (`system`, `load`, `read`, `script`, `other`, `spent`, `refused`). With `Agent(..., budget_tokens=N)` or `--budget N`, a skill body, file or script output that would push the run past N is replaced by an `error: context budget ...` message. A refused skill is not marked as loaded, so its files and scripts stay locked; a script still runs, only its output is withheld. The system prompt is always sent, so `spent` can end slightly above N.

## Routing eval

At level 1 the model sees only each skill's description, so the description decides whether the right skill gets loaded. Two tools check that:

```bash
PYTHONPATH=src python3 -m skills_agent.routing          # lint descriptions; --json, --skills-dir
```

| Rule | Flags |
| --- | --- |
| R1-short | fewer than 12 words |
| R2-no-trigger | no "Use when ..." clause |
| R3-vague | words like "helps with", "various", "stuff", "anything" |
| R4-first-person | "I", "my", "we" instead of third person |
| R5-overlap | two descriptions with a content word Jaccard score above 0.35 |

The shipped skills lint clean; the closest pair is commit-message / team-glossary at 0.07. Lint issues are warnings: the skill still loads, the command exits 1.

The quiz now also has a two skill task (glossary plus unit conversion in one question) and three near misses that share words with a description but need no skill ("Convert this sentence to the passive voice", "What does the acronym NASA stand for?", "In one sentence, what is a git commit?"). After the scenarios it prints a per skill table (tp, fp, fn, precision, recall), exact routing, how many no-skill runs stayed without a skill, and the lint result. Low precision means a description is too broad, low recall means it is too narrow.

## Skills

| Skill | What it teaches the model |
| --- | --- |
| `team-glossary` | Internal acronyms (BHX, ORCA, Q-Gate, Tidepool) the model cannot know otherwise |
| `commit-message` | The team's Conventional Commits format |
| `unit-converter` | Conversion factors and a 2 decimal rounding rule |
| `incident-severity` | Severity levels and paging rules; the body points to `references/severity-matrix.md`, which holds the actual table (level 3) |
| `ticket-checksum` | Completes or validates ticket IDs like `HX-40217` by running `scripts/check_letter.py`, the only script it is allowed to run |
| `broken_skill` | Deliberately invalid (underscore in the name); discovery rejects it |

Add your own: create `skills/<name>/SKILL.md` where `<name>` is lowercase with hyphens and matches the `name:` field.

```markdown
---
name: my-skill
description: What it does and when to use it, in one or two sentences.
---

# Instructions the model follows after loading the skill
```

## Demo

What a fresh checkout shows (output from the 2026-10-28 run, paths shortened):

```text
$ PYTHONPATH=src python3 -m skills_agent list
commit-message     0 files  0 scripts  Writes git commit messages in the team's Conventional Commits style. U...
incident-severity  1 files  0 scripts  Classify a production incident or outage into the team's severity leve...
team-glossary      0 files  0 scripts  Definitions of the internal acronyms and code names used by the team (...
ticket-checksum    1 files  1 scripts  Complete or validate a team ticket ID such as HX-40217 by computing it...
unit-converter     0 files  0 scripts  Converts between metric and imperial units for length, weight and temp...
5 skills, 1 rejected
  rejected: broken_skill: name must be lowercase letters, digits and single hyphens, not starting or ending with a hyphen

$ PYTHONPATH=src python3 -m skills_agent doctor --offline
[OK  ] python: 3.10.12 (needs 3.10+)
[OK  ] skills roots: .../week_02_skills_agent/skills
[OK  ] valid skills: 5: commit-message, incident-severity, team-glossary, ticket-checksum, unit-converter
[WARN] rejected skills: broken_skill: name must be lowercase letters, ...
[OK  ] descriptions: lint clean
[OK  ] script runners: python /usr/bin/python3; /bin/sh found
[WARN] ollama: skipped (--offline)
doctor: OK
```

With Ollama running, `python3 -m skills_agent "Checkout is down for 40% of users. How severe is this?"` should show `incident-severity` loaded and `references/severity-matrix.md` read on the first line, then an answer naming the colour code from that file.

## Results

`python3 quiz/quiz_model.py --fake --json results/fake.json` on 2026-10-28, then `--table results/fake.json`:

| model | date | total | level 2 | level 3 | script | two skills | no skill | near miss | exact routing | cli | avg s | avg tokens |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fake | 2026-10-28 | 12/12 | 5/5 | 1/1 | 1/1 | 1/1 | 1/1 | 3/3 | 12/12 | 4/4 | 0.0 | 1056 |
| qwen3:4b | not run yet | | | | | | | | | | | |

The fake model is scripted to route perfectly, so its row checks the harness: every skill, file and script is reachable, the answers really come from the disclosed text, and the CLI routes the same as the library. Average context was about 1,056 tokens per scenario against 1,316 for pasting every skill.

Real model: the daily automation runs in a VM that cannot reach Ollama on the Mac, so the `qwen3:4b` row is open. On the Mac:

```bash
python3 quiz/quiz_model.py --json results/qwen3_4b.json
python3 quiz/quiz_model.py --model llama3.2 --json results/llama3_2.json
python3 quiz/quiz_model.py --table results/*.json      # paste the rows above
```

Each report keeps every scenario's loaded skills, files, scripts and answer, so a failure can be explained without rerunning. The scenarios most likely to trip a small model, untested so far: the near misses (loading `unit-converter` for "convert this sentence") and the two skill task (stopping after the first skill).

## Tests and quiz

```bash
python3 -m pytest -q                       # fake LLM, no Ollama needed
python3 quiz/quiz_model.py --fake          # check the harness
python3 quiz/quiz_model.py                 # ask qwen3:4b; checks it loads the right skill
python3 quiz/quiz_model.py --model llama3.2 --only BHX
python3 quiz/quiz_model.py --fake --budget 1000   # see what a tight budget refuses
python3 quiz/quiz_model.py --only "near miss"     # only the near miss scenarios
python3 quiz/quiz_model.py --json results/x.json  # also save a JSON report
python3 quiz/quiz_model.py --table results/*.json # Markdown results table from reports
```

After the scenarios the quiz runs four CLI checks in process (`list`, `validate`, `inspect ticket-checksum`, and `run --json` on the BHX question with the same model) and fails if the CLI routes differently from the library.

A quiz scenario passes only if the model loaded exactly the expected skills, read exactly the expected skill files, ran exactly the expected scripts with exit code 0, and its answer contains text that exists only in the skill body, the referenced file or the script output. Each line also shows the estimated tokens the run used, and the summary compares the average with pasting every skill.
