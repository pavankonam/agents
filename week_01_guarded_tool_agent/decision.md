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
