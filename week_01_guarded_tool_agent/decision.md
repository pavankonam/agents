# Decision Log: Guarded Tool Agent

Each entry: what was decided, why, and what else was considered. New entries are appended at the bottom.

## D1. Project topic: tool permissioning for local agents (2026-10-15)

**Decision:** Build an agent whose tool calls all pass through a policy and an audit log.
**Why:** Tool calling is now standard in local models, and MCP made it easy to hand agents powerful tools. Safeguards (least privilege, approvals, audit logs) are the main 2026 theme in agent engineering and are rarely shown in small, readable code.
**Alternatives:** A RAG agent (well covered already), a multi agent debate demo (less practical), a computer use agent (needs vision models too heavy for a laptop).

## D2. LLM runtime: Ollama, local only (2026-10-15)

**Decision:** Use Ollama's `/api/chat` with native `tools` support.
**Why:** Free, runs offline on a Mac, exposes tool calling in the same shape as hosted APIs, and the user already has it set up.
**Alternatives:** llama.cpp server (more setup), LM Studio (GUI first), hosted free tiers (need keys, rate limits, not local).

## D3. Default model: `qwen3:4b` (2026-10-15)

**Decision:** Default to `qwen3:4b`, configurable with `GUARDED_AGENT_MODEL`.
**Why:** Small enough for a laptop, reliable at emitting tool calls. `llama3.2:3b` and `gemma` variants also work.
**Alternatives:** 8B+ models are better but slower for daily iteration.

## D4. Talk to Ollama with plain HTTP, no SDK (2026-10-15)

**Decision:** `OllamaClient` uses `urllib` from the standard library.
**Why:** Zero dependencies for the core, so tests and the agent run anywhere. The request body is tiny and stable.
**Alternatives:** The `ollama` Python package. Nice, but one more dependency that can change shape.

## D5. Pluggable LLM client with a FakeClient (2026-10-15)

**Decision:** The agent depends on a `LLMClient` protocol with one method, `chat(messages, tools)`. A `FakeClient` replays scripted responses.
**Why:** Lets every test run without a model and makes the daily automation deterministic. Swapping models or runtimes later touches one file.
**Alternatives:** Mocking HTTP calls (brittle) or requiring Ollama in tests (slow, flaky).

## D6. Tools declared as Python functions plus JSON schema (2026-10-15)

**Decision:** A `Tool` dataclass holds `name`, `description`, `parameters` (JSON schema) and `func`. The registry turns them into the Ollama tool format.
**Why:** The schema is what the model sees, so it is written explicitly rather than inferred. The same object will later wrap MCP tools.

## D7. Safe calculator, no `eval` (2026-10-15)

**Decision:** The calculator parses expressions with `ast` and only allows numbers and arithmetic operators.
**Why:** `eval` on model output is exactly the kind of risk this project is about. Even the demo tools should be safe.

## D8. Errors go back to the model, not up the stack (2026-10-15)

**Decision:** Unknown tools, bad arguments and tool exceptions become a `tool` message with an `error:` prefix.
**Why:** Gives the model a chance to recover, and keeps one bad call from killing the run. The same path will carry policy denials on day 2.

## D9. `max_steps` guard, default 6 (2026-10-15)

**Decision:** The loop stops after 6 model turns and returns a clear "step limit reached" result.
**Why:** Small models sometimes loop on tool calls. A hard cap keeps runs bounded.

## D10. Three verdicts: allow, ask, deny (2026-10-16)

**Decision:** Each tool in `policy.json` gets one verdict. `allow` runs, `ask` runs only after an approval callback says yes, `deny` never runs.
**Why:** It matches how people already think about agent permissions (the allow / ask / deny model used by coding agents and MCP clients) and is small enough to audit by eye.
**Alternatives:** Numeric risk scores (hard to reason about), role based access (overkill for one user on a laptop).

## D11. Fail closed everywhere (2026-10-16)

**Decision:** The policy default is `deny`. An `Agent` built without a policy denies every tool. A tool marked `ask` with no approver is denied. An approver that raises is treated as a no. Unknown verdicts or rule types in `policy.json` raise `ValueError` at load time.
**Why:** A forgotten setting or a typo must never widen what the agent can do. Tests opt in to `Policy.allow_all()` explicitly.
**Alternatives:** Default `allow` with a warning (convenient but the exact mistake this project is about).

## D12. Argument rules can only make a verdict stricter (2026-10-16)

**Decision:** Rules (`path_within`, `pattern`, `max_length`, `one_of`) are checked before the verdict is applied. A violation turns the call into `deny` and the approver is never asked.
**Why:** The model controls the arguments, so arguments must never be able to upgrade a verdict. Skipping the approver on a rule violation also avoids training the human to click yes on obviously bad calls.
**Alternatives:** Asking the human on violations (approval fatigue), allow rules that grant access (makes bypasses possible).

## D13. `path_within` resolves symlinks and `..` before comparing (2026-10-16)

**Decision:** Both the root and the target are passed through `Path.resolve()` and the target must equal the root or have it as a parent. Relative roots resolve against the folder of `policy.json`.
**Why:** String prefix checks are the classic sandbox escape (`workspace/../secret`, `workspace_evil/`, symlinks). Day 3 file tools depend on this.
**Alternatives:** `os.path.commonpath` on unresolved strings (misses symlinks), chroot (not portable to a Mac without root).

## D14. Denials go back to the model as a tool message (2026-10-16)

**Decision:** A blocked call produces `error: denied by policy: <reason>. Do not retry the same call...` as the tool result, and the system prompt tells the model not to repeat denied calls.
**Why:** Same path as D8: the run continues and the model can explain or choose another approach. The explicit "do not retry" text reduces loops on small models; `max_steps` still caps them.

## D15. Every call leaves a PolicyDecision (2026-10-16)

**Decision:** `Agent._guarded_call` is the only place a tool runs. It returns a `PolicyDecision` (tool, arguments, verdict, reason, approved) for every call, including unknown tools (recorded as `deny`), and `AgentResult.decisions` holds them in order.
**Why:** It is the success criterion "no tool runs without a recorded policy verdict", and it is exactly the data the day 4 audit log will write.

## D16. Two layers of path confinement for file tools (2026-10-17)

**Decision:** `policy.json` gives `read_file`, `list_dir` and `write_file` a `path_within: workspace` rule, and the tools themselves (`files.py`, `Workspace.resolve`) also resolve every path and refuse anything outside the workspace.
**Why:** The policy is configuration and can be edited, loosened or replaced with `Policy.allow_all()`. The tool level check makes the sandbox hold even then (defence in depth), while the policy check still blocks escapes before a human is ever asked (D12). Both use `Path.resolve()`, so `..`, absolute paths and symlinks are handled the same way in both layers.
**Alternatives:** Policy only (one typo opens the disk), tool only (escapes would reach the approver and would not show up as `deny` verdicts).

## D17. Verdicts for the file tools: read and list allow, write ask (2026-10-17)

**Decision:** Shipped `policy.json` marks `read_file` and `list_dir` as `allow` and `write_file` as `ask`, plus a `max_length` rule on `content` (100000 chars).
**Why:** Reading inside a sandbox is low risk and small models need it to be frictionless. Writing changes state, so a human approves each write. No delete tool exists at all: the safest permission is a tool that is never registered.
**Alternatives:** `ask` for reads too (approval fatigue), a `delete_file` tool behind `ask` (not needed for any milestone; day 7 tests that a prompt injection asking for deletion has nothing to call).

## D18. Size limits and text only reads (2026-10-17)

**Decision:** `read_file` returns at most 20000 bytes and appends `[truncated: showed N of M bytes]`; files with a NUL byte in the first 1 KB are refused as binary. `write_file` refuses content over 100000 bytes. `list_dir` shows at most 200 entries.
**Why:** A small local model has a small context window, and dumping a large or binary file into it wastes the context and confuses the model. Saying that output was truncated keeps the model honest about what it saw.

## D19. Sandbox errors become tool errors (2026-10-17)

**Decision:** `SandboxError` subclasses `ValueError`, and `ToolRegistry.call` turns any `ValueError` into `error: <tool>: <message>`.
**Why:** Same principle as D8: a blocked path is reported to the model so it can explain or correct itself; the run never crashes.

## D20. Workspace is a folder in the project, configurable (2026-10-17)

**Decision:** The CLI and `quiz_model.py` use `week_01_guarded_tool_agent/workspace/` (override with `GUARDED_AGENT_WORKSPACE`). It ships with a sample `notes.txt` used by the quiz.
**Why:** A known folder with known content makes the real model quiz deterministic. If the override points somewhere other than the policy's `path_within` root, the tool layer still confines writes to the override folder, so the worst case is extra denials, never extra access.

## D21. JSONL, one event per line, appended per event (2026-10-18)

**Decision:** `audit.py` writes one JSON object per line to an append only file, opening and closing the file for every event. Event types: `run_start`, `model_reply`, `tool_decision`, `tool_result`, `run_end`, `run_error`. Each has `ts` (UTC, ms), `run_id` (12 hex chars) and `seq` (0, 1, 2 ... within a run).
**Why:** JSONL can be appended without rewriting, read with `jq` or `grep`, and a crash can damage at most the last line. Opening per event puts each line on disk before the next step runs, which matters more than speed for a log of a few dozen lines per run. `seq` makes missing or duplicated lines detectable.
**Alternatives:** SQLite (atomic, but not human readable and harder to diff), Python `logging` (formats text, not structured events), one JSON array per run (must be rewritten, lost on crash).

## D22. The verdict is logged before the tool runs (2026-10-18)

**Decision:** `Agent._guarded_call` writes `tool_decision` (tool, arguments, verdict, reason, approved) right after the policy decides and before the tool is called; `tool_result` follows with `ran` and the output, including denial messages.
**Why:** The success criterion is "no tool runs without a recorded policy verdict". If the verdict were written with the result, a tool that hangs or kills the process would leave no record. Tested by a spy tool that reads the log while it runs.

## D23. Long strings are clipped in the log, not in the run (2026-10-18)

**Decision:** Any string over 2000 chars in an event (file contents, tool output, model text) is stored as its first 2000 chars plus `...[clipped N chars]`. The agent and the tools still see the full values.
**Why:** One `write_file` of 100000 chars would otherwise dominate the log. The audit question is "what was attempted and was it allowed", which the first 2000 chars and the length answer. Clipping only the log copy keeps behaviour identical with and without auditing.
**Alternatives:** Hash the content (proves identity but hides what was written), store full values (log bloat, and secrets copied around in full).

## D24. Audit is optional for the library, always on for the CLI and quiz (2026-10-18)

**Decision:** `Agent(audit=None)` writes nothing (decisions are still in `AgentResult.decisions`). The CLI always appends to `audit_logs/<UTC date>.jsonl` (override with `GUARDED_AGENT_AUDIT_DIR`), and `quiz_model.py` always logs to a temp file (or `--audit-log PATH`) and fails a scenario whose run is incomplete in the log. `audit_logs/` and `*.jsonl` stay gitignored.
**Why:** Unit tests and library users should not get files they did not ask for, while every real run is audited. Checking the log in the quiz turns the success criterion into a test against the real model too. Logs can contain file contents, so they never go to GitHub.

## D25. Replay checks integrity, not just formatting (2026-10-18)

**Decision:** `replay(path, run_id_prefix)` (CLI: `python -m guarded_agent replay <log> [run_id]`) prints each run as a timeline (`[step] model asks / policy -> RAN|BLOCKED / result / answers`, then `end`), skips malformed lines with a count, and adds `WARNING:` lines from `check_run` when seq numbers have gaps, a run never finished, or a tool result has no verdict before it.
**Why:** A replay that silently shows a damaged log would hide exactly the case an audit is for. A failed LLM call is logged as `run_error` (and still raised), so "never finished" really means the process died.

## D26. MCP client written on the standard library, stdio only (2026-10-19)

**Decision:** `mcp.py` implements the client side of MCP itself: start the server with `subprocess.Popen`, send newline delimited JSON-RPC 2.0 on stdin, read replies on a background thread, do `initialize` (protocol `2025-06-18`) plus `notifications/initialized`, then `tools/list` (following `nextCursor`, at most 50 pages) and `tools/call`. One request is in flight at a time, each with a timeout (default 30 s). Requests from the server (sampling, roots) are answered with "not supported".
**Why:** Keeps the zero dependency rule (D4) and the whole client readable in one file. Stdio is how almost every local MCP server is launched, and the agent only needs tools, not resources or prompts.
**Alternatives:** The official `mcp` Python SDK (async, many dependencies, changes often), HTTP transport (needs a running service, not needed for local servers).

## D27. MCP tools are registered as `<server>__<tool>` (2026-10-19)

**Decision:** Each wrapped tool is named server name plus `__` plus tool name, both cleaned to `[A-Za-z0-9_-]`, and its description starts with `[MCP server '<name>']`. The server's `inputSchema` is passed to the model unchanged (anything that is not an object schema becomes an empty object schema).
**Why:** Two servers can both have a `read_file`, and a server must never be able to shadow a built in tool (the registry also rejects duplicates). A visible prefix lets the policy, the audit log and the human approver see where a tool comes from.
**Alternatives:** Raw names (collisions and shadowing), a dot separator (not allowed in tool names by some models).

## D28. MCP tools take the exact same guarded path (2026-10-19)

**Decision:** Wrapped MCP tools are plain `Tool` objects in the `ToolRegistry`, so every call goes through `Agent._guarded_call`: argument rules, verdict, approver, `tool_decision` in the audit log before the call is sent. Unlisted MCP tools get the policy default (`deny`). A denied call is never sent to the server.
**Why:** The project's whole point is one choke point. A second code path for "external" tools would be the first place a bypass appears. Tested by checking the client's sent requests: a denied `demo__shell_exec` never appears in them.

## D29. Glob patterns for tool names in policy.json (2026-10-19)

**Decision:** Keys in `tools` may contain `*`, `?` or `[...]`. Lookup order: exact name, then the matching pattern with the most literal characters, then `default`. The decision reason says which pattern matched (`via pattern 'demo__*'`). Shipped policy: `demo__*` is `ask`, `demo__word_count` is `allow` with a `max_length` rule, `demo__shell_exec` is `deny`.
**Why:** An MCP server can expose dozens of tools that change between versions. A per server pattern like `server__*: ask` keeps new tools behind a human by default, while exact entries still pin down the risky or the trusted ones. Specificity, not file order, decides, so reordering the JSON cannot change a verdict.
**Alternatives:** Per server sections in the policy (a second format to learn), regex keys (harder to read, easy to over match), first match wins (order dependent).

## D30. A stdlib demo MCP server with a canary tool (2026-10-19)

**Decision:** `demo_mcp_server.py` is a tiny MCP server (word_count, reverse, shell_exec, crash, fail) used by tests, `quiz_model.py` and the README. `shell_exec` runs nothing; it only returns `CANARY: ...`. The quiz fails any scenario whose tool results contain `CANARY`. `DEMO_MCP_PAGE_SIZE` and `DEMO_MCP_SLOW` exercise pagination and timeouts.
**Why:** Tests and the daily run need a real subprocess speaking real MCP without Node or network. A canary turns "the deny rule held" into something checkable against the real model too, without ever giving the model a real shell.

## D31. Treat MCP servers as untrusted (2026-10-19)

**Decision:** Servers start with a minimal environment (`PATH`, `HOME`, `LANG`, `LC_ALL`, `TMPDIR`, `SYSTEMROOT` plus the config's own `env`), stderr is discarded, results are flattened to text (non text content is described, not inlined) and capped at 20000 chars, and a timeout, crash or JSON-RPC error becomes `MCPError`, which the registry turns into an `error: ...` tool message. `connect()` closes already started servers if a later one fails, and the CLI closes all servers when the run ends.
**Why:** A third party server should not inherit tokens like `GITHUB_TOKEN` from the shell, should not flood a small model's context, and should not be able to crash or hang the agent. Same "errors go back to the model" rule as D8 and D19.
