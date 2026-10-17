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

## Day 2 (2026-10-16)

**Q8. A tool is marked `allow` but the model passes `path: "../secrets.txt"` and the tool has a `path_within: workspace` rule. What happens?**
A: Argument rules are checked before the verdict, so the call becomes `deny` with reason `argument rule: ...`, the tool never runs and the approver is not asked.
Check: `policy.py` `Policy.check`, tests `test_rule_violation_denies_even_allowed_tool_and_skips_approver`, `test_path_within`. Ran `Policy.check` on `../a`: `deny`. **PASS**

**Q9. A tool is `ask` but no approver was passed to the Agent. Does it run?**
A: No. `Policy.decide` appends "no approver configured, treated as deny" and `approved` stays False.
Check: `policy.py` `Policy.decide`, test `test_ask_without_approver_is_denied`. Ran it: reason `tool 'x' is ask; no approver configured, treated as deny`. **PASS**

**Q10. What does an `Agent` do if you forget to pass a policy?**
A: It builds `Policy(default="deny")`, so every registered tool is blocked (fail closed, D11).
Check: `agent.py` `Agent.__init__`, test `test_agent_without_policy_fails_closed`. **PASS**

**Q11. How would a symlink inside the workspace that points outside be handled by `path_within`?**
A: Both paths are `resolve()`d, which follows the symlink, so the real target lies outside the root and the call is denied.
Check: `policy.py` `ArgRule.violation`, test `test_path_within_blocks_symlink_escape`. **PASS**

**Day 2 score: 4/4 (running total 11/11)**

## Day 3 (2026-10-17)

**Q12. With the shipped `policy.json`, what happens to `write_file(path="../x", content="a")` and to `write_file(path="a.txt", content="a")`?**
A: The first breaks the `path_within: workspace` rule, so it is `deny` and no human is asked. The second passes the rules and gets the tool's verdict, `ask`.
Check: `policy.json`, `policy.py` `Policy.check`, test `test_write_escape_never_reaches_the_human`. Ran `Policy.check`: `deny`, `ask`. **PASS**

**Q13. If someone runs the agent with `Policy.allow_all()`, can `read_file` read `../policy.json`?**
A: No. The tool itself calls `Workspace.resolve`, which raises `SandboxError`, and the model gets `error: read_file: path '../policy.json' is outside the workspace`.
Check: `files.py` `Workspace.resolve`, `tools.py` `ToolRegistry.call`, test `test_tool_layer_blocks_escape_even_with_allow_all`. Ran it: exactly that message. **PASS**

**Q14. The model calls `list_dir` with no `path` argument. Does the `path_within` rule block it?**
A: No. Rules skip missing arguments (`ArgRule.violation` returns None), so the verdict is `allow`, and the tool defaults to `"."`, the workspace root, which is inside the sandbox.
Check: `policy.py` `ArgRule.violation`, `files.py` `list_dir`. Ran it: verdict `allow`, output `notes.txt  (file)`. **PASS**

**Q15. What does the model see when it reads a 20001 byte text file?**
A: The first 20000 bytes followed by `[truncated: showed 20000 of 20001 bytes]`.
Check: `files.py` `MAX_READ_BYTES`, test `test_read_truncates_large_files_and_refuses_binary`. Ran it on a 20001 byte file: matches. **PASS**

**Day 3 score: 4/4 (running total 15/15)**
