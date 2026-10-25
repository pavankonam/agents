# Decision Log: Skills Agent

Each entry: what was decided, why, and what else was considered. New entries are appended at the bottom.

## D1. Project topic: Agent Skills with progressive disclosure (2026-10-22)

**Decision:** Build a small runtime for Agent Skills (`SKILL.md` folders) on a local model.
**Why:** The 2026-10-22 research pass showed attention shifting to the harness (skills, memory, evals, sandboxes) rather than the model, and the Agentic AI Foundation took Agent Skills on as an open project. Skills are a natural follow on to week 01: week 01 controlled *what tools* an agent may call, week 02 controls *what instructions* enter its context and when.
**Alternatives:** An agent memory layer (big topic, hard to finish and evaluate in 7 days on a laptop), sandboxed eval harness with microVMs (needs Docker and heavier setup), a multi agent orchestrator (well covered already).

## D2. LLM runtime: Ollama, local only (2026-10-22)

**Decision:** Same as week 01: Ollama `/api/chat` with native tool calling.
**Why:** Free, offline, the user already runs it. Keeps the series consistent.

## D3. Default model: `qwen3:4b`, override with `SKILLS_AGENT_MODEL` (2026-10-22)

**Decision:** Default to `qwen3:4b`.
**Why:** Small and reliable at tool calls. A 4B model is also the honest test for skills: if routing works on 4B with only descriptions, it works on bigger models.

## D4. Plain HTTP to Ollama, no SDK (2026-10-22)

**Decision:** `urllib` only, as in week 01.
**Why:** Zero runtime dependencies; tests run anywhere.

## D5. FakeClient for tests and `--fake` quiz runs (2026-10-22)

**Decision:** Every test and the fake quiz use scripted responses.
**Why:** Deterministic daily automation, no model needed.

## D6. Copy `llm.py` from week 01 instead of importing it (2026-10-22)

**Decision:** Each week is self contained, so `llm.py` is copied with only the env var renamed.
**Why:** A reader can open one folder and run it. Sharing code across weeks would couple projects and make week 01 harder to change.
**Alternatives:** A shared `common/` package (cleaner, but breaks "one folder, one project").

## D7. Three levels of disclosure, built one per day (2026-10-22)

**Decision:** Level 1 catalog (name and description in the system prompt), level 2 body via `load_skill`, level 3 resources via a later `read_skill_file` tool.
**Why:** This is the core idea of Agent Skills: pay context only for what a task needs. Building one level at a time keeps each day testable.

## D8. Own frontmatter parser instead of PyYAML (2026-10-22)

**Decision:** Parse the YAML subset skills use: `key: value`, single and double quotes, `|` and `>` block scalars, indented continuation lines, one level nested mapping for `metadata`, comments.
**Why:** Keeps the agent dependency free. Real `SKILL.md` frontmatter is small and flat. Anything outside the subset raises `SkillError` with the line, so nothing is silently misread.
**Alternatives:** PyYAML (one dependency, full YAML, but also full YAML surprises such as `no` becoming `False`).

## D9. One tool on day 1: `load_skill(name)` with an `enum` of names (2026-10-22)

**Decision:** The tool schema lists valid skill names as an `enum`.
**Why:** Small models misspell names; an enum lets Ollama's tool format constrain or at least hint the choice. Unknown names still get a helpful error listing what exists. A repeated load returns a short note instead of the body again, so a looping model does not flood its own context.

## D10. Validation: hard errors vs warnings (2026-10-22)

**Decision:** Errors (skill rejected): missing name or description, name not lowercase and single hyphens, longer than 64 chars, not matching its folder, description over 1024 chars, compatibility over 500 chars, metadata not a mapping, broken frontmatter. Warnings (skill kept): unknown fields, very short description, empty body.
**Why:** Errors are the rules from the Agent Skills format that would make a skill ambiguous or unroutable. Warnings are style issues a human should fix but that do not break loading.

## D11. Discovery: several roots, first root wins on duplicates (2026-10-22)

**Decision:** `SkillLibrary.discover(*roots)` scans each root's subfolders in order; a duplicate name keeps the first and records the second in `rejected`. Hidden folders are skipped.
**Why:** Lets a user put personal skills before project skills to override them, and makes the override visible instead of silent.

## D12. Catalog as escaped XML (2026-10-22)

**Decision:** `<available_skills><skill><name/><description/></skill></available_skills>` with HTML escaping.
**Why:** Clear boundaries for the model and a description cannot break out of its element. Bodies are never in the catalog; a test asserts that.

## D13. Quiz checks body knowledge, not just the tool call (2026-10-22)

**Decision:** Each `quiz_model.py` scenario expects text that only the skill body contains (for example "Blue Heron Expansion"), and fails if extra skills were loaded.
**Why:** A model that calls `load_skill` and then ignores the result would pass a tool only check. Extra loads waste context, which is the thing this project measures.

## D14. `read_skill_file` only works for skills that are already loaded (2026-10-23)

**Decision:** Level 3 reads are refused with `error: skill ... is not loaded. Call load_skill first` until the model has called `load_skill` for that skill.
**Why:** Progressive disclosure is an order, not just three functions. The body is what tells the model which file matters and why; reading files blind would skip that and waste context on the wrong file. It also keeps `loaded_skills` an honest record of what the model used.
**Alternatives:** Let any file be read at any time (simpler, but a small model could bypass the body entirely); load the body automatically on first file read (hides a step the quiz wants to measure).

## D15. Path confinement: reject first, then resolve and compare (2026-10-23)

**Decision:** `resolve_resource` rejects empty, absolute (`/x`, `C:/x`), any `..` part, hidden parts (`.env`, `.git/...`) and `SKILL.md` itself before touching the disk. Backslashes count as separators. Then it resolves the path with symlinks followed and requires the real file to sit under the real skill folder and be a regular file. A symlink that stays inside the folder is allowed.
**Why:** Two layers. The string checks give the model a clear reason for the common mistakes. The resolve check is the real guarantee: it also catches a symlink planted inside the skill that points to `~/.ssh` or a sibling skill. `SKILL.md` is refused so the body only ever arrives through `load_skill`, which is what tracks loads.
**Alternatives:** Only the resolve check (safe, but errors are less helpful); a chroot or sandbox (overkill for reading text, revisit for scripts on day 3).

## D16. Size cap with truncation, and text only (2026-10-23)

**Decision:** At most 16,000 bytes per read (about 4k tokens). Larger files are cut at the cap (never inside a UTF-8 character) and the tool message ends with `[truncated: ...]`. Files with a NUL byte or invalid UTF-8 are refused.
**Why:** A 4B model with an 8k to 32k window cannot afford one huge reference file. Truncating with a visible note is more useful than a flat refusal: the model still gets the top of the file, which is usually the table of contents or the rule it needs. Binary content is noise for a text model.
**Alternatives:** Refuse big files (unhelpful), page through with an offset argument (more tool calls for a small model to get right; may come back if day 4 budgets need it).

## D17. Offer `read_skill_file` only when a skill bundles files, and list files on load (2026-10-23)

**Decision:** `Agent.tools()` adds `read_skill_file` only if at least one skill has files besides `SKILL.md`, and its `skill` enum contains only those skills. `load_skill` appends a `<skill_files>` list (names only, at most 50, hidden files and symlinks out) after the body.
**Why:** Every tool schema costs context on every turn and is one more thing a small model can call wrongly. Listing names on load tells the model what exists without paying for the contents, which is exactly level 3 of progressive disclosure. Errors from `read_skill_file` repeat the list so the model can correct a wrong path.
**Alternatives:** Always offer the tool (simpler schema, wasted tokens); put file lists in the catalog (leaks level 3 into level 1).

## D18. Level 3 quiz scenario whose answer is only in the reference file (2026-10-23)

**Decision:** New `incident-severity` skill. Its body only says "read `references/severity-matrix.md`"; the colour codes (Code Crimson and so on) exist only in that file. The quiz scenario expects "Crimson" and requires exactly that file to be read. A test asserts the expected text is neither in the catalog nor in the body.
**Why:** Same idea as D13 one level deeper: the answer can only be right if the model actually followed the pointer and read the file.

## D19. Scripts are gated by the skill's own `allowed-tools` (2026-10-24)

**Decision:** A script runs only if the skill's frontmatter grants it: `allowed-tools: run_skill_script` allows every script in `scripts/`, `run_skill_script(scripts/check.py)` allows one, and the part in brackets may be a glob (`scripts/*.py`). Entries are matched with `fnmatchcase`; anything else in `allowed-tools` (for example `Bash(git:*)`) grants nothing here.
**Why:** The Agent Skills format already has `allowed-tools` for "tools this skill is pre-approved to use", so the permission lives next to the script it covers and is visible in review. Default is deny: a skill that only ships reference files can never become executable by someone dropping a `.py` into it. The bracket form mirrors how `Bash(...)` patterns look in existing skills, so it reads naturally.
**Alternatives:** A global allow list in the agent (permission far from the skill), approval prompts per run like week 01 (good, but this week is about disclosure, and the week 01 policy layer could wrap this later), allow all scripts (unsafe).

## D20. Interpreter from the extension, no shell, args as a list (2026-10-24)

**Decision:** Only `scripts/*.py` (run with the agent's own Python in isolated mode, `-I -B`) and `scripts/*.sh` (run with `/bin/sh`) are runnable. Shebangs and the exec bit are ignored. The command is an argv list passed to `subprocess.Popen` with `shell=False`. Args must be a list of at most 16 strings of at most 500 chars without NUL; numbers are turned into strings, one bare string becomes one arg, and a string that looks like a JSON list is parsed (small models send that).
**Why:** With no shell, `$(...)`, `;` and quotes inside an arg are plain text, so the model cannot inject commands even if a user tricks it. Choosing the interpreter ourselves means a script cannot pick an arbitrary binary through its first line. `-I` keeps the user's `PYTHONPATH` and site packages out.
**Alternatives:** Execute the file directly (shebang decides, any language, but also any binary), `shell=True` with quoting (one bug away from injection).

## D21. Same confinement as level 3, plus `scripts/` only, and load first (2026-10-24)

**Decision:** `resolve_script` reuses `resolve_resource` (no absolute paths, `..`, hidden parts, `SKILL.md`, or symlinks that leave the folder), then requires the real path to be under `scripts/`. `run_skill_script` is refused until the skill is loaded, exactly like `read_skill_file` (D14). The tool is offered only when some skill has a permitted script, and its `skill` enum lists only those skills. Errors list the scripts the skill may run.
**Why:** One path checker means one place to get right. Keeping scripts in `scripts/` matches the Agent Skills layout and stops a skill's reference or asset files from being executed. Load first keeps the order of progressive disclosure: the body says when and how to run the script.
**Alternatives:** Allow scripts anywhere in the folder (blurs data and code).

## D22. Process limits: timeout, capped output, minimal environment (2026-10-24)

**Decision:** Each run gets a 10 second wall clock timeout, after which the whole process group is killed (`start_new_session=True` plus `killpg`, so child processes die too). stdout and stderr go to temporary files and at most 8,000 bytes of each are read back, with a `[truncated]` note. stdin is `/dev/null`, the working directory is the skill folder, and the environment has only `PATH`, `LANG`, `LC_ALL`, `PYTHONIOENCODING` and `PYTHONDONTWRITEBYTECODE` (so tokens in the user's shell, like `GITHUB_TOKEN`, never reach the script).
**Why:** A bad or hostile script must not hang the agent, flood the model's context or read secrets from the environment. Writing to files instead of pipes keeps memory bounded even if a script prints gigabytes before the timeout. This is not a sandbox: a script can still read files the user can read. That limit is stated in the README.
**Alternatives:** `resource` limits on CPU and memory (not portable to macOS for memory), a container or microVM (real isolation, but needs Docker; out of scope for a 7 day local project).

## D23. Script results are data, recorded, and checked by the quiz (2026-10-24)

**Decision:** The tool message is `<script_result skill=... script=... exit_code=...>` with `<stdout>` and, if not empty, `<stderr>`; a timeout shows `exit_code="timeout"`. A crash or non zero exit is a normal result the model can explain, not an exception. Every run is recorded in `AgentResult.ran_scripts` as `skill/script exit=N`. New `ticket-checksum` skill: the check letter for `HX-40217` (`C`) exists only in the script output, so the quiz scenario requires that exactly that script ran with exit 0, that its output contained `HX-40217-C`, and that the answer repeats it.
**Why:** Same idea as D13 and D18, one level further: the model can only pass if it really ran the script and used its output. A weighted mod 23 check letter is something a 4B model gets wrong by hand, which is the realistic reason a skill ships a script.

## D24. Estimate tokens as ceil(characters / 4), no tokenizer (2026-10-25)

**Decision:** `budget.estimate_tokens` returns `ceil(len(text) / 4)`. Tool schemas are estimated from their compact JSON, because Ollama sends them with every request.
**Why:** The numbers are used to compare two strategies and to enforce a limit, never to bill. Both sides use the same estimate, so the comparison holds even if the absolute count is off by 10 to 20 percent. A real tokenizer would mean a model specific download (or a third party package) for each model, and this project is standard library only. Ollama does return `prompt_eval_count` after a call, but a budget has to decide before the text is sent.
**Alternatives:** `tiktoken` (OpenAI tokenizer, wrong for Qwen and Llama anyway), Ollama's tokenize endpoint (needs a running server, so tests could not run without Ollama), word count (worse for code and XML).

## D25. Report progressive disclosure against "paste every skill", with a projection (2026-10-25)

**Decision:** `context_report(library)` gives per skill costs (level 1 catalog entry, level 2 body, level 3 files), the progressive cost before any load (system prompt plus tool schemas), with one average skill used, and with everything loaded, and the cost of one prompt that pastes every body and every bundled text file. It also projects both strategies to 5, 20, 50 and 100 skills of the same average size. `python3 -m skills_agent.budget [--json]` prints it.
**Why:** The honest finding with the five shipped skills: before any load progressive is 30% cheaper (919 vs 1,316 tokens), with one skill used it is only 12% cheaper (1,155), and if a task needed every skill it would cost more (2,100), because the rules and the three tool schemas are a fixed overhead of about 600 tokens. The projection shows why the pattern still matters: at 20 skills one used skill costs about 2,200 tokens against 4,900 pasted, at 100 skills about 8,000 against 23,800. Showing the losing case keeps the claim honest.
**Alternatives:** Only report the saving (hides the overhead), measure with real Ollama runs only (not repeatable in tests).

## D26. A per run budget meters everything the harness adds to the context (2026-10-25)

**Decision:** `Agent(..., budget_tokens=N)` creates a fresh `ContextBudget` for each `run`. It charges the system prompt, the user task and the tool schemas (`system`), each `load_skill` result (`load`), each `read_skill_file` result (`read`), each script result (`script`), and errors, notes and refusals (`other`). `AgentResult.context` holds the summary: limit, spent, the five kinds and the refused list. Without a limit the meter still runs, so every run reports its cost. The model's own replies are not charged, because the harness does not control them.
**Why:** Small local models have short context windows (often 4k to 8k by default in Ollama), and the point of progressive disclosure is to stay inside them. Metering per kind shows where the tokens went. The system part is always sent even if it alone is over the limit, since a run without the prompt is useless; that and the short refusal messages are the only ways `spent` can go past the limit.
**Alternatives:** Count the whole message list each turn (charges the same prompt again every step, which is not how the context grows), stop the run when the limit is hit (the model could still answer from what it already has).

## D27. Refuse a disclosure that does not fit, as a tool error the model can act on (2026-10-25)

**Decision:** Before a `load_skill` or `read_skill_file` result is returned, its estimate is checked against what is left. If it does not fit, the model gets `error: context budget: <what> needs about N tokens but only M of L are left in this run. Answer with what you already have, or say which information is missing.` A refused load does not mark the skill as loaded, so its files and scripts stay locked (D14, D21). A script cannot be checked before it runs, so the script runs, `ran_scripts` records it, and only its output is withheld if it does not fit.
**Why:** Refusing as a normal tool message keeps the loop simple and lets the model explain the gap instead of guessing, which matches how errors already work (flow.md step 7). Not marking a refused skill as loaded keeps the disclosure order intact: you cannot read level 3 of a skill whose level 2 you never saw. For scripts the honest option is to say that it ran but its output was withheld, rather than pretend it did not run.
**Alternatives:** Truncate the body to fit (a half skill is worse than none, instructions at the end get lost), evict an earlier skill (more complex, and the model would lose instructions it is following), refuse to run scripts when less than the 8 KB worst case is left (would block cheap scripts under any tight budget).
