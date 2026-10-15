# Self Quiz: Guarded Tool Agent

Each day the automation answers these from memory, then checks the answer against the code and docs. A FAIL means either the answer or the docs were wrong, and it gets fixed the same day.

## Day 1 (2026-10-15)

**Q1. What happens if the model calls a tool that does not exist?**
A: `ToolRegistry.call` returns `"error: unknown tool '<name>'. Available: ..."`, which is added as a `tool` message so the model can recover. Nothing is raised.
Check: `tools.py` `ToolRegistry.call`, test `test_unknown_tool_is_reported_not_raised`. **PASS**

**Q2. How does the agent decide it is finished?**
A: When a model reply contains no tool calls, its text is the final answer (`stopped_reason = "final_answer"`).
Check: `agent.py` `Agent.run`. **PASS**

**Q3. What stops an agent that keeps calling tools forever?**
A: `max_steps` (default 6). After that many model turns it returns `"Stopped: step limit reached"` with `stopped_reason = "max_steps"`.
Check: `agent.py`, test `test_max_steps_guard`. **PASS**

**Q4. Why does the calculator not use `eval`?**
A: Model output is untrusted. `safe_eval` walks the `ast` and only allows numeric constants and arithmetic operators, and caps exponents at 100, so code like `__import__('os')` is rejected.
Check: `tools.py` `safe_eval`, test `test_safe_eval_rejects_code`. **PASS**

**Q5. Which default model and how do you change it?**
A: `qwen3:4b`, overridable with the `GUARDED_AGENT_MODEL` environment variable or `--model` in `quiz_model.py`.
Check: `llm.py` `DEFAULT_MODEL`, `decision.md` D3. **PASS**

**Q6. Why is there no Ollama SDK dependency?**
A: The core uses `urllib` to keep zero dependencies so tests run anywhere (decision D4).
Check: `llm.py`, `requirements.txt`. **PASS**

**Q7. How can the tests run without a model?**
A: `FakeClient` replays scripted `LLMResponse` objects and records the messages it received.
Check: `llm.py` `FakeClient`. **PASS**

**Day 1 score: 7/7**
