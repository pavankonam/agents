# Flow: Guarded Tool Agent

Status: **Day 2**. Solid boxes exist today, dashed boxes are planned (day in brackets).

```mermaid
flowchart TD
    U[User task] --> A[Agent.run]
    A --> M[LLM client.chat<br/>OllamaClient or FakeClient]
    M -->|final text, no tool calls| R[Return answer + decisions]
    M -->|tool_calls| G[Agent._guarded_call]
    G -->|tool not registered| UK[deny: unknown tool]
    G --> RU{Argument rules<br/>path_within / pattern / max_length / one_of}
    RU -->|violation| E[deny: error message to model]
    RU -->|ok| P{{Verdict from policy.json<br/>default deny}}
    P -->|allow| T[ToolRegistry.call]
    P -->|deny| E
    P -->|ask| H[Approver callback<br/>console_approver in CLI]
    H -->|yes| T
    H -->|no / none / raised| E
    G --> D[PolicyDecision recorded<br/>AgentResult.decisions]
    D -.-> L[(Audit log JSONL  [day 4])]
    T -->|tool result message| A
    E -->|tool error message| A
    UK -->|tool error message| A
    A -->|steps > max_steps| S[Stop: step limit reached]

    subgraph Tools
      C[calculator]
      CT[current_time]
      F[file tools  [day 3]]
      MCP[MCP server tools  [day 5]]
    end
    T --- Tools

    classDef planned stroke-dasharray: 5 5;
    class L,F,MCP planned;
```

## How it works today

1. `Agent.run(task)` starts a message list with a system prompt and the user task.
2. Each step sends the messages and the tool schemas to the LLM client.
3. If the reply has no tool calls, its text is the final answer.
4. Otherwise every tool call goes through `Agent._guarded_call`, the only place a tool can run:
   * unknown tool: recorded as `deny`, the model gets `error: unknown tool ...`;
   * argument rules from `policy.json` are checked first; any violation is a `deny` and the approver is not asked;
   * then the tool's verdict applies: `allow` runs, `deny` blocks, `ask` calls the approver (no approver, a "no", or an approver error all block).
   * Blocked calls return `error: denied by policy: <reason>` to the model so it can explain instead of crashing.
5. Each call leaves a `PolicyDecision` (tool, arguments, verdict, reason, approved) in `AgentResult.decisions`.
6. After `max_steps` model turns the run stops with `stopped_reason = "max_steps"`.

`Policy.from_file("policy.json")` loads the policy. Unlisted tools use `default` (shipped as `deny`), and relative `path_within` roots resolve against the policy file's folder.
