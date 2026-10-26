# Flow: Skills Agent

Status: **Day 5**. Every box exists in the code. The dashed arrow is the per kind meter that ends up in `AgentResult.context`. The bottom part is the routing eval, which runs outside the agent loop.

```mermaid
flowchart TD
    D[(skills/ folders<br/>each with SKILL.md)] --> DS[SkillLibrary.discover<br/>skills.py]
    DS --> PF[parse_frontmatter<br/>YAML subset, no PyYAML]
    PF --> V{validate<br/>name rules, folder match,<br/>length limits}
    V -->|errors| RJ[rejected list<br/>never shown to the model]
    V -->|ok, maybe warnings| LIB[SkillLibrary.skills]
    LIB --> CAT[catalog: XML of<br/>name + description only<br/>Level 1]
    U[User task] --> A[Agent.run<br/>agent.py]
    CAT --> SP[System prompt]
    SP --> A
    A --> M[LLM client.chat<br/>OllamaClient or FakeClient<br/>tools: load_skill, plus read_skill_file<br/>if any skill bundles files]
    M -->|final text| R[AgentResult<br/>answer, loaded_skills,<br/>read_files, ran_scripts, tool_calls]
    M -->|tool_calls| DP{dispatch by tool name}
    DP -->|load_skill| L{load_skill name}
    DP -->|unknown tool| E
    L -->|no name /<br/>unknown skill| E[error message to model]
    L -->|already loaded| N[short note, no body]
    L -->|ok| B["&lt;skill name=...&gt; body<br/>+ &lt;skill_files&gt; names only<br/>Level 2"]
    DP -->|read_skill_file| RF{skill loaded?}
    RF -->|no| E
    RF -->|yes| RR{resolve_resource<br/>no abs, no .., no hidden,<br/>not SKILL.md, real path<br/>inside skill folder}
    RR -->|refused or missing| E2[error + list of files]
    RR -->|ok| RD["read_resource: text only,<br/>16 KB cap, truncated note<br/>&lt;skill_file&gt; Level 3"]
    E --> A
    E2 --> A
    N --> A
    DP -->|run_skill_script| RS{skill loaded?}
    RS -->|no| E
    RS -->|yes| RSV{resolve_script<br/>same checks as level 3,<br/>inside scripts/, .py or .sh,<br/>allowed-tools grants it,<br/>args: list of strings}
    RSV -->|refused| E3[error + scripts it may run]
    RSV -->|ok| RUN["subprocess, no shell<br/>cwd = skill folder, minimal env,<br/>no stdin, 10 s timeout kills group,<br/>8 KB per stream"]
    RUN --> SR["&lt;script_result exit_code=...&gt;<br/>stdout, stderr"]
    E3 --> A
    A -->|max_steps reached| X[stopped: step limit]
    B --> BG
    RD --> BG
    SR --> BG
    BG{ContextBudget<br/>fits in budget_tokens?<br/>budget.py}
    BG -->|yes| A
    BG -->|no| E4[error: context budget<br/>skill not loaded, file not shown,<br/>script output withheld]
    E4 --> A
    BG -.->|meter per kind| R
    LIB --> LN[lint_library<br/>routing.py: R1 short, R2 no trigger,<br/>R3 vague, R4 first person,<br/>R5 overlap > 0.35]
    Q[(quiz scenarios<br/>skill tasks, two skill task,<br/>near misses)] --> A
    R -->|expected vs loaded_skills| RM[routing_metrics<br/>per skill tp, fp, fn,<br/>precision, recall,<br/>exact, abstain]
    RM --> QR[quiz report]
    LN --> QR
```

## How it works

1. **Discovery.** Every subfolder of `skills/` with a `SKILL.md` is parsed. The frontmatter must have a valid `name` (lowercase, digits, single hyphens, at most 64 chars, equal to the folder name) and a `description` (at most 1024 chars). Broken skills go to `rejected` with a reason and never reach the model.
2. **Level 1.** The system prompt contains only the catalog: each skill's name and description in XML. No instructions.
3. **Level 2.** The model has the `load_skill` tool. Its `name` parameter is an enum of valid names. The tool returns the skill's Markdown body wrapped in `<skill name="...">`, followed by a `<skill_files>` list of the other files in the folder (names only). Loading the same skill again returns a short note instead.
4. **Level 3.** If any skill bundles files, the model also gets `read_skill_file(skill, path)`. It only works after that skill was loaded. The path must be relative, without `..` or hidden parts, not `SKILL.md`, and its real location (symlinks followed) must be inside the skill folder. At most 16 KB of UTF-8 text comes back in `<skill_file>`; longer files are cut with a `[truncated]` note. Every successful read is recorded in `AgentResult.read_files`.
5. **Scripts.** If a skill's frontmatter says `allowed-tools: run_skill_script` (or `run_skill_script(scripts/x.py)` for one script), the model also gets `run_skill_script(skill, script, args)`. It only works after `load_skill`. The script must be a `.py` or `.sh` file in the skill's `scripts/` folder, pass the same path checks as level 3, and be granted by `allowed-tools`. It runs with no shell (args are a list of strings), the skill folder as working directory, no stdin, a minimal environment and a 10 second timeout that kills the whole process group. Up to 8 KB of stdout and stderr come back in `<script_result exit_code=...>`. Every run is recorded in `AgentResult.ran_scripts`.
6. **Context budget.** Every run has a `ContextBudget` (`budget.py`). It charges the system prompt, task and tool schemas, then every tool result, estimating tokens as characters / 4. With `budget_tokens` set, a skill body, file or script output that would push the run past the limit is replaced by `error: context budget ...`; a refused skill is not marked loaded. The per kind totals end up in `AgentResult.context`. `python3 -m skills_agent.budget` prints the cost of each level and compares it with pasting every skill into the prompt.
7. **Routing eval.** `routing.py` lints every description (too short, no "Use when" clause, vague words, first person, or too similar to another skill) because the description is all the model sees at level 1. `quiz/quiz_model.py` runs skill tasks, a two skill task and near misses (tasks that share words with a description but need no skill), then compares each run's `loaded_skills` with the expected set and prints per skill precision and recall, exact routing and how many no-skill runs stayed without a skill. `python3 -m skills_agent.routing` prints the lint report alone.
8. **Answer.** The loop ends when the model replies without tool calls, or after `max_steps` (default 6).
9. **Errors** (unknown skill, missing argument, unknown tool, file or script refused) go back to the model as tool messages starting with `error:`, so it can recover.
