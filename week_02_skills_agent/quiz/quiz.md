# Self Quiz: Skills Agent

Each day the automation answers these from memory, then checks the answer against the code and docs. A FAIL means either the answer or the docs were wrong, and it gets fixed the same day.

## Day 1 (2026-10-22)

**Q1. What does the model see about a skill before it calls `load_skill`?**
Answer: Only its name and description, inside `<available_skills>` XML in the system prompt. The body is not included.
Verified: `SkillLibrary.catalog()` in `skills.py` emits only `<name>` and `<description>`; `Agent.system_prompt()` formats it into `SYSTEM_TEMPLATE`. Tests `test_catalog_has_descriptions_but_no_bodies` and `test_system_prompt_has_catalog_only` assert body text is absent. **PASS**

**Q2. A folder `skills/broken_skill/` has `name: broken_skill`. What happens to it?**
Answer: Discovery rejects it because underscores break the name rule (lowercase letters, digits, single hyphens). It is added to `SkillLibrary.rejected`, is not in the catalog or the tool enum, and `load_skill("broken_skill")` returns `error: no skill named ...`.
Verified: `NAME_RE` in `skills.py`, `test_discover_shipped_skills_rejects_broken`, `test_rejected_skill_cannot_be_loaded`. **PASS**

**Q3. What happens if the model calls `load_skill` twice for the same skill?**
Answer: The second call returns a short `note:` saying it is already loaded, without the body, and `loaded_skills` lists it once.
Verified: `Agent._load` checks `if skill.name in loaded`; `test_second_load_is_a_short_note`. **PASS**

**Q4. Two skill roots both contain a skill named `dup`. Which one is used?**
Answer: The one from the first root passed to `discover`. The second is recorded in `rejected` as a duplicate.
Verified: `SkillLibrary.discover` (`if skill.name in lib.skills` then reject), `test_discover_first_root_wins_and_missing_root`. **PASS**

**Q5. How does `description: >` with two indented lines get parsed?**
Answer: Folded: the lines are joined with single spaces. `|` would keep the newlines.
Verified: `parse_frontmatter` joins with `" "` when `rest[0] == ">"`; `test_parse_folded_literal_quoted_and_nested`. **PASS**

Day 1 result: 5/5 PASS.
