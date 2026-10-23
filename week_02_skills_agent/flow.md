# Flow: Skills Agent

Status: **Day 2**. Every box exists in the code. Dashed boxes are planned for later days.

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
    M -->|final text| R[AgentResult<br/>answer, loaded_skills,<br/>read_files, tool_calls]
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
    B --> A
    RD --> A
    A -->|max_steps reached| X[stopped: step limit]
    RD -.->|day 3| SC[run_skill_script]
```

## How it works

1. **Discovery.** Every subfolder of `skills/` with a `SKILL.md` is parsed. The frontmatter must have a valid `name` (lowercase, digits, single hyphens, at most 64 chars, equal to the folder name) and a `description` (at most 1024 chars). Broken skills go to `rejected` with a reason and never reach the model.
2. **Level 1.** The system prompt contains only the catalog: each skill's name and description in XML. No instructions.
3. **Level 2.** The model has the `load_skill` tool. Its `name` parameter is an enum of valid names. The tool returns the skill's Markdown body wrapped in `<skill name="...">`, followed by a `<skill_files>` list of the other files in the folder (names only). Loading the same skill again returns a short note instead.
4. **Level 3.** If any skill bundles files, the model also gets `read_skill_file(skill, path)`. It only works after that skill was loaded. The path must be relative, without `..` or hidden parts, not `SKILL.md`, and its real location (symlinks followed) must be inside the skill folder. At most 16 KB of UTF-8 text comes back in `<skill_file>`; longer files are cut with a `[truncated]` note. Every successful read is recorded in `AgentResult.read_files`.
5. **Answer.** The loop ends when the model replies without tool calls, or after `max_steps` (default 6).
6. **Errors** (unknown skill, missing argument, unknown tool, file refused) go back to the model as tool messages starting with `error:`, so it can recover.
