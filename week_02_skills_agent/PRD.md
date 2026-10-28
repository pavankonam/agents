# PRD: Skills Agent

**Week:** 02 (2026-10-22 to 2026-10-28)
**Stack:** Python 3.10+, Ollama (local, free), standard library only

## 1. Why this project

The research pass on 2026-10-22 showed the focus in agent engineering moving from the model to the **harness** around it: skills, memory, permissions, evals and sandboxes. One concrete sign: the Agentic AI Foundation announced *Agent Skills* as one of four new open projects (with Open Responses, OpenEnv and OpenSandbox). Agent Skills are folders with a `SKILL.md` file (YAML frontmatter plus Markdown instructions) that an agent loads only when a task needs them.

The key idea is **progressive disclosure**: the model sees a short catalog (name and description of each skill), loads a skill's full instructions on demand, and reads extra files from the skill folder only if those instructions point to them. That keeps the context small, which matters most for small local models with short context windows.

This project builds a readable Skills runtime on a free local model, and measures whether a 4B model actually picks the right skill.

Sources: [AAIF announcement](http://www.prnewswire.com/news-releases/agentic-ai-foundation-announces-four-new-projects-agent-skills-open-responses-openenv-and-opensandbox-302916689.html), [Open Source Radar 2026-10-18: the agent operations layer](https://dev.to/widechaos/open-source-radar-2026-10-18-the-agent-operations-layer-not-the-model-127o), [awesome-harness-engineering](https://github.com/ai-boost/awesome-harness-engineering).

## 2. Goals

1. Parse and validate `SKILL.md` files against the Agent Skills rules (name format, folder match, length limits) with no third party YAML library.
2. Three levels of disclosure: catalog in the system prompt, `load_skill` tool for the body, `read_skill_file` for bundled resources.
3. Run bundled skill scripts safely (no shell, timeout, only scripts inside the skill folder).
4. Measure context cost per level, and how often the model routes to the right skill (`quiz/quiz_model.py`).
5. A CLI to list, validate, inspect and run skills.

## 3. Non goals

* No cloud or paid LLM APIs.
* Not a marketplace or installer. Skills are local folders.
* No web UI.

## 4. Users

A developer who wants a local agent that can be taught new procedures by dropping a folder into `skills/`, and who wants to see what each skill costs in context.

## 5. Daily milestones

* [x] **Day 1 (Thu 10/22):** Research, PRD, decision log, flow, quiz. `SKILL.md` parser (frontmatter subset: scalars, quotes, `|` and `>` blocks, nested `metadata`) and validator, `SkillLibrary.discover` with rejected list, XML catalog (level 1), agent loop with a single `load_skill` tool (level 2), three example skills plus one deliberately broken skill, LLM clients copied from week 01, tests, quiz_model with skill routing scenarios.
* [x] **Day 2 (Fri 10/23):** Level 3 resources: `read_skill_file(skill, path)` confined to a loaded skill's folder (no `..`, no symlink escape, size cap), skill with a `references/` file that the body points to.
* [x] **Day 3 (Sat 10/24):** Skill scripts: `run_skill_script(skill, script, args)` runs files from `scripts/` with `subprocess` (no shell, timeout, output cap), gated by the skill's `allowed-tools`.
* [x] **Day 4 (Sun 10/25):** Context budget: token estimates per level, a report comparing progressive disclosure with "paste every skill into the prompt", and a per run budget that refuses loads past a limit.
* [x] **Day 5 (Mon 10/26):** Routing eval: more scenarios including near misses and two skill tasks, per skill precision and recall in `quiz_model.py`, a description linter that flags vague descriptions.
* [x] **Day 6 (Tue 10/27):** CLI: `list`, `validate`, `inspect`, `run`, `doctor`, with `--json`, exit codes and `--skills-dir` (multiple roots).
* [x] **Day 7 (Wed 10/28):** Close out: real model results table, README demo, retro in decision.md, project closed in state.json.

## 6. Success criteria

* `python3 -m pytest -q` passes with the fake LLM, no Ollama needed.
* `python3 quiz/quiz_model.py --fake` passes; on `qwen3:4b` the routing scenarios pass or failures are explained in the README.
* An invalid skill never reaches the catalog, and the reason is reported.
* The system prompt never contains a skill body until `load_skill` was called.
