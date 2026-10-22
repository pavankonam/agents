# Flow: Skills Agent

Status: **Day 1**. Every box exists in the code. Dashed boxes are planned for later days.

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
    A --> M[LLM client.chat<br/>OllamaClient or FakeClient<br/>tools: load_skill with name enum]
    M -->|final text| R[AgentResult<br/>answer, loaded_skills, tool_calls]
    M -->|tool_calls| L{load_skill name}
    L -->|unknown tool / no name /<br/>unknown skill| E[error message to model]
    L -->|already loaded| N[short note, no body]
    L -->|ok| B["&lt;skill name=...&gt; body &lt;/skill&gt;<br/>Level 2"]
    E --> A
    N --> A
    B --> A
    A -->|max_steps reached| X[stopped: step limit]
    B -.->|day 2| RF[read_skill_file<br/>Level 3 resources]
    B -.->|day 3| SC[run_skill_script]
```

## How it works

1. **Discovery.** Every subfolder of `skills/` with a `SKILL.md` is parsed. The frontmatter must have a valid `name` (lowercase, digits, single hyphens, at most 64 chars, equal to the folder name) and a `description` (at most 1024 chars). Broken skills go to `rejected` with a reason and never reach the model.
2. **Level 1.** The system prompt contains only the catalog: each skill's name and description in XML. No instructions.
3. **Level 2.** The model has one tool, `load_skill`. Its `name` parameter is an enum of valid names. The tool returns the skill's Markdown body wrapped in `<skill name="...">`. Loading the same skill again returns a short note instead.
4. **Answer.** The loop ends when the model replies without tool calls, or after `max_steps` (default 6).
5. **Errors** (unknown skill, missing name, unknown tool) go back to the model as tool messages starting with `error:`, so it can recover.
