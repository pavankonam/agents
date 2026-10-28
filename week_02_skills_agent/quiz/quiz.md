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

## Day 3 (2026-10-24)

**Q10. `team-glossary` has no `allowed-tools`. The model loads it and calls `run_skill_script("team-glossary", "scripts/x.py")`. What happens?**
Answer: The call is refused before anything runs. `team-glossary` is not even in the `skill` enum of `run_skill_script`, because the tool only lists skills with a permitted script. If the call is made anyway, the agent returns an `error:` message (here `no file 'scripts/x.py'`, and for an existing but ungranted script `does not allow running ...`) followed by `Scripts this skill may run: none`. `ran_scripts` stays empty.
Verified: `Agent.tools()` with the shipped skills gives the run enum `['ticket-checksum']` (checked by hand today); `resolve_script` checks the path first, then `script_permission`; `Agent._run_script` appends the runnable list on `SkillError`. Tests `test_skill_without_allowed_tools_cannot_run`, `test_refused_script_lists_runnable_ones`, `test_tool_offered_only_for_skills_with_permitted_scripts`. **PASS**

**Q11. The model passes the args `["a b", "$(touch pwned)", "; rm -rf /"]`. What does the script receive?**
Answer: Exactly three arguments, unchanged: `a b`, `$(touch pwned)` and `; rm -rf /`. There is no shell (`shell=False`, argv list), so nothing is expanded or executed, and no `pwned` file appears.
Verified: `run_script` builds `INTERPRETERS[suffix] + [path] + check_args(args)` and calls `Popen(..., shell=False)`; `test_args_are_not_shell_parsed` asserts the echoed list and that `pwned` does not exist. **PASS**

**Q12. A skill script calls `time.sleep(30)`. What does the model see, and how long does the agent wait?**
Answer: About 10 seconds (`SCRIPT_TIMEOUT`). Then the whole process group is killed and the model gets `<script_result ... exit_code="timeout">` with a `[stopped: the script ran longer than 10 seconds]` line. `ran_scripts` records `skill/scripts/slow.py exit=timeout`.
Verified: `run_script` uses `proc.wait(timeout=...)`, then `os.killpg`; `format_result` writes `timeout` and the stopped note. Tests `test_timeout_kills_the_script` (0.5 s limit, finishes in well under 5 s) and `test_failed_and_timed_out_runs_are_reported`. **PASS**

**Q13. Pavan has `GITHUB_TOKEN` exported in his shell. Can a skill script read it?**
Answer: No. The script gets a fresh environment with only `PATH`, `LANG`, `LC_ALL`, `PYTHONIOENCODING` and `PYTHONDONTWRITEBYTECODE`, and Python runs with `-I`. It can still read files Pavan can read, because this is not a full sandbox (D22, README).
Verified: `_minimal_env()` in `scripts.py`; `test_cwd_env_and_stdin` sets `SECRET_TOKEN` in the test process and the script prints `None`. **PASS**

Day 3 result: 4/4 PASS. Earlier questions rechecked against today's code: Q1 to Q8 still PASS. Q9 is still PASS as written for the day 2 skill set, but with today's `ticket-checksum` skill (which bundles `scripts/check_letter.py`) the shipped `read_skill_file` enum is now `["incident-severity", "ticket-checksum"]`; `test_tool_schema_enumerates_skill_names` was updated to match.

## Day 4 (2026-10-25)

**Q14. How does the agent count tokens, and why is that good enough here?**
Answer: `estimate_tokens(text)` is `ceil(len(text) / 4)`, 0 for empty text; tool schemas are estimated from their compact JSON. It is only used to compare strategies and to enforce a limit, and both sides use the same estimate, so no model specific tokenizer is needed (D24).
Verified: `estimate_tokens` and `tools_tokens` in `budget.py`; `test_estimate_tokens_is_ceil_chars_over_four` (`"abcde"` is 2, 400 chars are 100) and `test_tools_tokens_empty_and_nonempty`. **PASS**

**Q15. With the shipped skills, is progressive disclosure always cheaper than pasting every skill into the prompt?**
Answer: No. Before any load it is 919 vs 1,316 estimated tokens (30% cheaper), with one average skill used 1,155 (12% cheaper), but a task that loads every skill and file costs 2,100, more than pasting, because the rules and three tool schemas add about 600 fixed tokens. The projection shows the gap growing with more skills: at 100 skills about 8,033 vs 23,755.
Verified: ran `python3 -m skills_agent.budget` today and got exactly these numbers; `test_report_numbers_are_consistent` asserts base < pasted < all loaded and that the projected gap grows and ends positive. **PASS**

**Q16. `budget_tokens=950` and the model calls `load_skill("team-glossary")`. What happens, and can it then call `read_skill_file` on that skill?**
Answer: The system part (prompt, task, tool schemas, 924 tokens) is always sent. The 160 token body does not fit in the 26 left, so the model gets `error: context budget: load_skill team-glossary needs about 160 tokens but only 26 of 950 are left ...`, the body is not shown and the skill is not added to `loaded_skills`. So any later `read_skill_file` or `run_skill_script` for it fails with `is not loaded`. `context["refused"]` records it and `spent` ends at 970, a little over the limit, because the refusal message itself is charged as `other` (D26).
Verified: ran exactly this by hand today (output `spent 970, system 924, other 46, refused ['load_skill team-glossary needs 160']`); `Agent._load` calls `_over_budget` before `loaded.append`; tests `test_load_past_the_limit_is_refused_and_not_loaded` and `test_refused_load_keeps_files_locked`. **PASS**

**Q17. The script output does not fit in the remaining budget. Did the script run?**
Answer: Yes. A script cannot be priced before it runs, so it runs, `ran_scripts` records `ticket-checksum/scripts/check_letter.py exit=0`, but the model gets `error: context budget: output of ticket-checksum/scripts/check_letter.py ...` instead of the output, and `context["script"]` stays 0 (D27).
Verified: `Agent._run_script` appends to `ran` before calling `_over_budget("script", ...)`; `test_script_output_past_the_limit_is_withheld_but_run_is_recorded` asserts the error, that `HX-40217-C` is absent and the `ran_scripts` entry. **PASS**

Day 4 result: 4/4 PASS. Earlier questions rechecked against today's code: Q1 to Q13 still PASS. The system prompt and tool schemas did not change today (budget refusals are tool messages), so Q1, Q9 and Q10 hold as written; `SkillLibrary.catalog()` now builds its rows with the new `catalog_entry`, and `test_catalog_has_descriptions_but_no_bodies` still passes.

## Day 5 (2026-10-26)

**Q18. A skill's description is just `Helps with stuff.` Is it rejected, and what does the linter say?**
Answer: It is not rejected: discovery only rejects hard spec errors, and lint issues are warnings (D28). `lint_description` reports three issues: `R1-short` (3 words, at least 12), `R2-no-trigger` (no "Use when ..." clause) and `R3-vague` (`helps with, stuff`). `python3 -m skills_agent.routing` exits 1 because there are issues; with the shipped skills it reports 0 issues and exits 0.
Verified: ran `lint_description("x", "Helps with stuff.")` by hand today and got exactly those three codes; `test_cli_exit_codes_and_json` checks exit 1 and the codes in `--json`, `test_shipped_skills_lint_clean_and_far_apart` checks the shipped set. **PASS**

**Q19. On the NASA near miss the model loads `team-glossary` and then answers correctly. Does the scenario pass, and what changes in the routing table?**
Answer: It fails, because the loaded set must equal the expected set (empty), even though the answer text is right. In the table `team-glossary` gets one false positive: with the other scenarios perfect that is tp 3, fp 1, fn 0, precision 0.75, recall 1.00, and the abstain line becomes 3/4. The quiz exits 1.
Verified: `skills_ok` in `quiz_model.run` compares sorted lists; `routing_metrics` counts `got - want` as fp; `test_misrouting_model_lowers_precision` asserts the FAIL line, the row `team-glossary 3 1 0 0.75 1.00` and `without a skill 3/4`. **PASS**

**Q20. Why is "(near miss)" printed in the report but not part of the question?**
Answer: The label would tell the model not to load a skill, so the near miss would test nothing. Near misses are listed in a separate `NEAR_MISS` set; `label()` adds the prefix only for printing and for `--only` matching, and the agent gets the plain question (D30).
Verified: `Agent(...).run(question)` uses the raw tuple entry; `test_quiz_has_near_misses_and_a_two_skill_task` asserts no question contains "near miss" and that each one shares a content word with some description (`convert`, `acronym`, `git`/`commit`, checked by hand today); `test_only_near_miss_filter` runs 3/3. **PASS**

**Q21. The two skill task loads only `team-glossary` and answers `Blue Heron Expansion`. What does the quiz report?**
Answer: FAIL. The loaded set misses `unit-converter`, and the answer lacks the second expected part `8.05` (a tuple expected means every part must appear). In the metrics `unit-converter` gets a false negative; on that run alone its precision is `n/a` (never loaded) and recall 0.00, and exact routing is 0/1.
Verified: `answer_ok = all(...)` over `parts(expected)`; ran `routing_metrics([(["team-glossary","unit-converter"],["team-glossary"])])` by hand today (unit-converter precision None, recall 0.0, exact 0); `test_two_skill_task_fails_if_one_part_is_missing` and `test_unused_skill_has_undefined_ratios`. **PASS**

Day 5 result: 4/4 PASS. Earlier questions rechecked against today's code: Q1 to Q17 still PASS. No agent, prompt, tool or skill file changed today (routing.py and the quiz are outside the loop), so Q1, Q9 and Q10 hold as written and the Q15 numbers are unchanged (re-ran `python3 -m skills_agent.budget`: 919, 1,155, 2,100, 1,316). The day 1 to 4 quiz tests that read `expected` were updated to accept the new tuple form and still pass.

## Day 6 (2026-10-27)

**Q22. What do `python3 -m skills_agent validate` and `validate --strict` return on the shipped skills, and why?**
Answer: Both exit 1. `broken_skill` is rejected (underscore in the name), and `validate` fails on any rejected skill; the summary reads `5 valid, 1 errors, 0 warnings, 0 lint issues: FAIL`. `--strict` would also fail on frontmatter warnings or lint issues, but the shipped skills have none, so it fails for the same single reason. `list` on the same folder exits 0, because it is a view, not a check (D32).
Verified: ran both today (exit 1, and `strict exit 1`); `cmd_validate` sets `failed = bool(lib.rejected) or (args.strict and bool(warnings or lint))`; tests `test_validate_fails_on_rejected_skill` and `test_validate_clean_root_ok_and_strict_fails_on_lint` (a `Helps with stuff.` skill is exit 0 normally, exit 1 with `--strict`). **PASS**

**Q23. Ollama is not running and everything else is fine. What does `doctor` print and return? And with `--offline`?**
Answer: Six checks are `OK` except `rejected skills`, which is `WARN` (broken_skill), and `ollama` is `FAIL` with `Ollama is not reachable at http://localhost:11434 ... Start it with ollama serve`; the summary is `doctor: FAIL` and the exit code is 4, because Ollama is the only failing check. With `--offline` the Ollama check becomes `WARN skipped` and the exit code is 0 (D33).
Verified: ran `doctor` on the Mac shell today with no Ollama listening (exit 4, exactly that output) and `doctor --offline` (exit 0); `cmd_doctor` returns `EXIT_OLLAMA` when `failing == {"ollama"}`; `test_doctor_ollama_only_failure_is_exit_4` also covers a model that is not pulled (`ollama pull llama3.2`). **PASS**

**Q24. Two `--skills-dir` roots both contain `team-glossary`. Which copy does the agent use, and is anything reported?**
Answer: The copy in the first root given. The second is added to the rejected list as `duplicate skill name 'team-glossary', kept <first path>`, so `list` shows it under rejected (still exit 0) and `validate` would exit 1. A root that does not exist is also reported as rejected (`skills root does not exist`), and `doctor` marks it FAIL.
Verified: ran `list --skills-dir <tmp copy> --skills-dir skills` today (`5 skills, 2 rejected`, the duplicate line names the tmp copy as kept); `SkillLibrary.discover` keeps the first (D11); `test_multiple_roots_first_wins_and_missing_root_reported` and `test_doctor_missing_root_or_old_python_is_exit_1`. **PASS**

**Q25. What happens with `python3 -m skills_agent list my files`?**
Answer: `list` is a command name, so the argv is not rewritten to `run`; argparse rejects the extra words with `unrecognized arguments: my files` and the exit code is 2. To ask the agent a task that starts with a command word, write `run list my files`. Any other first word (for example `"What does BHX stand for?"`) is treated as `run` (D31).
Verified: ran it today (usage line, `error: unrecognized arguments: my files`, exit 2); `normalize` only prepends `run` when `argv[0]` is not in `COMMANDS` or help; `test_short_form_still_runs_and_step_limit_exit` asserts `normalize(["list"]) == ["list"]` and `normalize(["What is BHX?"]) == ["run", "What is BHX?"]`. **PASS**

Day 6 result: 4/4 PASS. Earlier questions rechecked against today's code: Q1 to Q21 still PASS. The agent loop, prompt, tools and skills did not change (the CLI wraps `Agent` and `SkillLibrary`), so Q1, Q9, Q10 hold and the Q15 numbers are unchanged. The day 4 test `test_main_budget_flag_validation` now goes through `cli.main` and still gets exit 2 for `--budget`, `--budget abc task`, `--budget 0 task` and `--budget 500` without a task. `quiz_model.py --fake` adds 4 CLI checks, 4/4 PASS.

## Day 7 (2026-10-28)

**Q26. How are the 12 scenarios grouped in the results table, and what does the fake row show?**
Answer: `kind()` checks in order: near miss (question in `NEAR_MISS`), no skill (no expected skill), two skills, script, level 3, else level 2. That gives level 2: 5, level 3: 1, script: 1, two skills: 1, no skill: 1 (`ready`), near miss: 3. The fake row from `results/fake.json` is `12/12` with every group full, exact routing 12/12, CLI 4/4 and about 1,056 tokens per scenario (D35).
Verified: ran `--fake --json results/fake.json` then `--table results/fake.json` today (row `| fake | 2026-10-28 | 12/12 | 5/5 | 1/1 | 1/1 | 1/1 | 1/1 | 3/3 | 12/12 | 4/4 | 0.0 | 1056 |`); `test_kind_groups_every_scenario` and `test_json_report_and_results_table`. **PASS**

**Q27. Ollama is down and you run `quiz_model.py --json results/qwen3_4b.json`. Is a report written?**
Answer: No. The preflight runs first and returns 4 with `PROBLEM: Ollama is not reachable ...`, before any scenario, so no file is written and an old report at that path stays as it was. A report only exists for a run that actually reached the model.
Verified: ran it on the Mac shell today with no Ollama listening (exit 4, `/tmp/q.json` not created); `write_report` is only called at the end of `run`, after the preflight `return 4`. **PASS**

**Q28. A real model answers the BHX question without loading any skill. What does the report record?**
Answer: That scenario row has `ok: false`, `loaded_skills: []` and the model's answer text; `passed` drops by one, and in `routing.per_skill` `team-glossary` gets `fn: 1`, so its recall falls. `--table` shows it under level 2. The quiz exits 1.
Verified: `test_failed_scenario_is_recorded_in_report` swaps `OllamaClient` for a model that replies "No idea." (exit 1, `passed` 0, `fn` 1, answer saved). **PASS**

**Q29. What does `--table` do with a missing or broken report file, or none?**
Answer: Prints `PROBLEM: cannot read report <path>: ...` and exits 2 for a missing file or invalid JSON; with no readable report it prints `No report files given` and exits 2. Nothing is printed as a partial table.
Verified: ran `--table nope.json` today (exit 2 with that message); `test_table_bad_or_missing_report` covers bad JSON, a missing file and an empty list. **PASS**

Day 7 result: 4/4 PASS. Earlier questions rechecked: Q1 to Q25 still PASS. The agent loop, prompt, tools, skills and CLI did not change today (only `quiz_model.py` and its tests), so Q1, Q9, Q10 hold and the Q15 numbers are unchanged (re-ran `python3 -m skills_agent.budget`: 919, 1,155, 2,100, 1,316). `doctor --offline` re-run today: OK with two warnings (broken_skill, Ollama skipped), exit 0. 184 tests pass.
