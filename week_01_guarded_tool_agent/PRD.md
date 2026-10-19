# PRD: Guarded Tool Agent

**Week:** 01 (2026-10-15 to 2026-10-21)
**Stack:** Python 3.10+, Ollama (local, free), optional MCP servers

## 1. Why this project

Agents moved from chat to action in 2025 and 2026: tool calling, computer use, and MCP servers that expose files, shells and APIs to a model. The open question is no longer "can an agent call tools" but "how do we stop it calling the wrong ones". The 2026 consensus safeguards are least privilege tool access, human approval for risky actions, and audited logs of everything an agent did.

Most tutorials skip that layer. This project builds a small, readable agent on a free local model where **every tool call passes through a permission policy and is written to an audit log**.

## 2. Goals

1. A working tool calling agent loop on Ollama (default model `qwen3:4b`, any tool capable model works).
2. A policy layer: each tool is `allow`, `ask` (human approval) or `deny`, with optional argument rules (for example "only paths inside `./workspace`").
3. A JSONL audit log of every model turn, tool request, policy verdict and result, plus a replay command.
4. Tools loaded from an MCP server over stdio, wrapped by the same policy.
5. An eval script (`quiz/quiz_model.py`) that checks the agent picks the right tools and that the policy blocks unsafe calls.

## 3. Non goals

* No cloud or paid LLM APIs.
* No web UI. A CLI is enough.
* Not a general framework. Small enough to read in one sitting.

## 4. Users

A developer who wants to run a local agent on their laptop and know exactly what it is allowed to do.

## 5. Daily milestones

* [x] **Day 1 (Thu 10/15):** PRD, decision log, flow, quiz. Core agent loop with a pluggable LLM client (`OllamaClient`, `FakeClient`), tool registry with JSON schemas, two safe tools (`calculator`, `current_time`), max step guard, tests.
* [x] **Day 2 (Fri 10/16):** Permission policy (`allow` / `ask` / `deny`) loaded from `policy.json`, argument rules, approval callback. Denied calls are reported back to the model instead of crashing.
* [x] **Day 3 (Sat 10/17):** File tools (`read_file`, `write_file`, `list_dir`) sandboxed to a workspace folder. Path rules enforced by the policy.
* [x] **Day 4 (Sun 10/18):** JSONL audit log for every step and a `replay` command that prints a run as a readable timeline.
* [x] **Day 5 (Mon 10/19):** MCP client: load tools from any stdio MCP server and route them through the policy. (Stdlib JSON-RPC client, `server__tool` names, glob patterns in `policy.json`, demo server with a denied canary tool.)
* [ ] **Day 6 (Tue 10/20):** CLI (`python -m guarded_agent "task"`), README demo, `quiz_model.py` scenarios against real Ollama.
* [ ] **Day 7 (Wed 10/21):** Hardening and close out: prompt injection test (a file that tells the agent to delete things), results table, retro.

## 6. Success criteria

* `pytest` passes with no model installed (fake client).
* With Ollama running, `quiz/quiz_model.py` passes at least 80% of scenarios on `qwen3:4b`.
* No tool runs without a recorded policy verdict.
* A `deny` rule can never be bypassed by the model's arguments (tested).

## 7. Risks

| Risk | Mitigation |
| --- | --- |
| Small local models call tools poorly | Clear tool descriptions, low temperature, step limit, model is configurable |
| Model loops forever | `max_steps` guard (default 6) |
| Ollama API changes | All Ollama code isolated in `llm.py` |
