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
