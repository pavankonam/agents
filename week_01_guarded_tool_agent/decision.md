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
