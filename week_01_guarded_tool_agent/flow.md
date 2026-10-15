# Flow: Guarded Tool Agent

Status: **Day 1**. Solid boxes exist today, dashed boxes are planned (day in brackets).

```mermaid
flowchart TD
    U[User task] --> A[Agent.run]
    A --> M[LLM client.chat<br/>OllamaClient or FakeClient]
    M -->|final text, no tool calls| R[Return answer]
    M -->|tool_calls| P{{Policy check<br/>allow / ask / deny  [day 2]}}
    P -.->|ask| H[Human approval  [day 2]]
    P -->|allow| T[ToolRegistry.call]
    P -.->|deny| E[error message to model]
    H -.-> T
    H -.-> E
    T --> L[(Audit log JSONL  [day 4])]
    E --> L
    T -->|tool result message| A
    E -->|tool error message| A
    A -->|steps > max_steps| S[Stop: step limit reached]

    subgraph Tools
      C[calculator]
      CT[current_time]
      F[file tools  [day 3]]
      MCP[MCP server tools  [day 5]]
    end
    T --- Tools

    classDef planned stroke-dasharray: 5 5;
    class P,H,E,L,F,MCP planned;
```

## How it works today

1. `Agent.run(task)` starts a message list with a system prompt and the user task.
2. Each step sends the messages and the tool schemas to the LLM client.
3. If the reply has no tool calls, its text is the final answer.
4. Otherwise each tool call is looked up in the `ToolRegistry` and executed. The result (or an `error:` string) is appended as a `tool` message, and the loop continues.
5. After `max_steps` model turns the run stops with `stopped_reason = "max_steps"`.

Every run returns an `AgentResult` with the answer, the full message list and the list of tool calls made, so tests and the quiz can check behaviour exactly.
