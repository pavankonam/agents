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

## Day 2 (2026-10-23)

**Q6. The model calls `read_skill_file("incident-severity", "references/severity-matrix.md")` before it ever called `load_skill`. What does it get back?**
Answer: An error saying the skill is not loaded and that it must call `load_skill` first. No file content is returned and `read_files` stays empty.
Verified: `Agent._read` checks `if skill.name not in loaded` before touching the file; `test_read_before_load_is_refused` asserts the message, that "Code Crimson" is absent and `read_files == []`. **PASS**

**Q7. A skill folder contains `references/escape.md`, a symlink to a file outside the skill. Can the model read it?**
Answer: No. The string checks pass (no `..`, relative), but `resolve_resource` follows the symlink and the real path is not under the real skill folder, so it raises `path ... resolves outside the skill folder`. The file is also left out of the `<skill_files>` list. A symlink whose target stays inside the folder is allowed.
Verified: `resolve_resource` (`root not in real.parents`), `list_resources` skips `p.is_symlink()`; tests `test_symlink_escape_is_refused`, `test_symlink_inside_the_folder_is_allowed`, `test_list_resources_skips_skill_md_hidden_and_symlinks`. **PASS**

**Q8. A reference file is 20,000 bytes. What reaches the model?**
Answer: The first 16,000 bytes (`RESOURCE_MAX_BYTES`), never cut inside a UTF-8 character, followed by a `[truncated: file is larger than the read limit]` line, inside `<skill_file skill=... path=...>`.
Verified: `read_resource` reads `max_bytes + 1` and slices; `Agent._read` appends the note. Checked by hand today with a 20,000 byte file: exactly 16,000 bytes of content and the note came back. Tests `test_size_cap_truncates`, `test_truncation_inside_multibyte_char_is_trimmed`, `test_truncation_note_reaches_the_model`. **PASS**

**Q9. With only `team-glossary`, `commit-message` and `unit-converter` installed, which tools does the model see?**
Answer: Only `load_skill`. `read_skill_file` is offered only when at least one skill bundles files besides `SKILL.md`, and its `skill` enum lists only those skills. With the shipped `skills/` folder today that is `["incident-severity"]`.
Verified: `Agent.tools()` and `_skills_with_files()`; `test_no_read_tool_when_no_skill_has_files`, `test_tool_schema_enumerates_skill_names`. **PASS**

Day 2 result: 4/4 PASS. Day 1 questions rechecked against today's code: Q1 to Q5 still PASS (Q1 now also covers `test_system_prompt_mentions_read_tool_and_no_file_content`).
