# Week 02: Skills Agent

A small agent that uses **Agent Skills** (folders with a `SKILL.md` file) on a **free local model through Ollama**. The model only sees each skill's name and description, and loads the full instructions when a task needs them (progressive disclosure). See [PRD.md](PRD.md) for the plan, [flow.md](flow.md) for how it works and [decision.md](decision.md) for why.

**Status:** Day 3 of 7. Skill parser and validator, discovery with rejected list, catalog in the system prompt (level 1), `load_skill` tool (level 2), `read_skill_file` for files bundled with a skill (level 3, confined to the skill folder), `run_skill_script` for scripts a skill permits in `allowed-tools` (no shell, timeout, output cap), five example skills, 123 tests.

## Run it

```bash
ollama pull qwen3:4b          # once
cd week_02_skills_agent
export PYTHONPATH=src

python3 -m skills_agent "What does BHX stand for?"
python3 -m skills_agent "Convert 26.2 miles to km"
python3 -m skills_agent "Checkout is down for 40% of users. How severe is this?"
python3 -m skills_agent "What is the full ticket ID with check letter for HX-40217?"
SKILLS_AGENT_MODEL=llama3.2 python3 -m skills_agent "Write a commit message for: add retry to the HTTP client"
```

The first line of output shows which skills the model loaded, which skill files it read and which skill scripts it ran.

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

## Tests and quiz

```bash
python3 -m pytest -q                       # fake LLM, no Ollama needed
python3 quiz/quiz_model.py --fake          # check the harness
python3 quiz/quiz_model.py                 # ask qwen3:4b; checks it loads the right skill
python3 quiz/quiz_model.py --model llama3.2 --only BHX
```

A quiz scenario passes only if the model loaded exactly the expected skills, read exactly the expected skill files, ran exactly the expected scripts with exit code 0, and its answer contains text that exists only in the skill body, the referenced file or the script output.
