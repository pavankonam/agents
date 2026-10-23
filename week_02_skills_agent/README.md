# Week 02: Skills Agent

A small agent that uses **Agent Skills** (folders with a `SKILL.md` file) on a **free local model through Ollama**. The model only sees each skill's name and description, and loads the full instructions when a task needs them (progressive disclosure). See [PRD.md](PRD.md) for the plan, [flow.md](flow.md) for how it works and [decision.md](decision.md) for why.

**Status:** Day 2 of 7. Skill parser and validator, discovery with rejected list, catalog in the system prompt (level 1), `load_skill` tool (level 2), `read_skill_file` for files bundled with a skill (level 3, confined to the skill folder), four example skills, 82 tests.

## Run it

```bash
ollama pull qwen3:4b          # once
cd week_02_skills_agent
export PYTHONPATH=src

python3 -m skills_agent "What does BHX stand for?"
python3 -m skills_agent "Convert 26.2 miles to km"
python3 -m skills_agent "Checkout is down for 40% of users. How severe is this?"
SKILLS_AGENT_MODEL=llama3.2 python3 -m skills_agent "Write a commit message for: add retry to the HTTP client"
```

The first line of output shows which skills the model loaded and which skill files it read.

## Three levels of disclosure

| Level | What the model sees | When |
| --- | --- | --- |
| 1 | Name and description of every skill | Always, in the system prompt |
| 2 | The `SKILL.md` body, plus the names of the other files in the folder | After `load_skill(name)` |
| 3 | One bundled file, for example `references/severity-matrix.md` | After `read_skill_file(skill, path)`, only for a loaded skill |

Level 3 reads are refused for absolute paths, `..`, hidden files, `SKILL.md` itself and symlinks that lead outside the skill folder. Files are capped at 16 KB of UTF-8 text; longer ones are truncated with a note.

## Skills

| Skill | What it teaches the model |
| --- | --- |
| `team-glossary` | Internal acronyms (BHX, ORCA, Q-Gate, Tidepool) the model cannot know otherwise |
| `commit-message` | The team's Conventional Commits format |
| `unit-converter` | Conversion factors and a 2 decimal rounding rule |
| `incident-severity` | Severity levels and paging rules; the body points to `references/severity-matrix.md`, which holds the actual table (level 3) |
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

A quiz scenario passes only if the model loaded exactly the expected skills, read exactly the expected skill files, and its answer contains text that exists only in the skill body or the referenced file.
